import os
import sys
import time
import numpy as np
from osgeo import gdal, ogr, osr
import threading
import queue # For thread-safe communication with GUI
import traceback

# --- Tkinter Imports ---
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# --- Configuration (Defaults for GUI) ---
DEFAULT_OUTPUT_NAME = "vectorized_output.gpkg"
# Updated terminology and defaults
DEFAULT_CONFIDENCE_THRESHOLD_BUILDING = 40.0 # Percentage (around 0.4)
DEFAULT_CONFIDENCE_THRESHOLD_ROAD = 40.0     # Percentage (around 0.4)
DEFAULT_MIN_AREA_BUILDING = 50.0
# REMOVED: DEFAULT_MAX_HOLE_AREA_BUILDING
DEFAULT_SIMPLIFY_BUILDING = 1.0
DEFAULT_MIN_AREA_ROAD = 20.0
DEFAULT_SIMPLIFY_ROAD = 1.5
DEFAULT_CHAIKIN_ITERATIONS_ROAD = 0

# --- GDAL/OGR Setup ---
gdal.UseExceptions()
ogr.UseExceptions()
# gdal.PushErrorHandler('CPLQuietErrorHandler') # Suppress warnings if needed

# --- Helper Functions for Processing (Mostly Unchanged, fill_small_holes removed) ---
# Added logger_queue argument for GUI feedback

def log_message(logger_queue, message):
    """Helper to put messages onto the GUI queue."""
    if logger_queue:
        # Ensure message is string and clean potential non-string inputs
        try:
            logger_queue.put(str(message))
        except Exception as e:
            # Fallback for weird objects that fail str() conversion
             try:
                 logger_queue.put(f"[Logging Error: Could not convert message to string - {type(message)} - {e}]")
             except: pass # Final fallback, do nothing
    else:
        print(message) # Fallback to console if queue isn't set

def get_raster_info(raster_ds, logger_queue=None):
    """Extracts key information from a GDAL Raster DataSource."""
    # ... (function remains the same as before) ...
    if not raster_ds:
        return None
    info = {
        'cols': raster_ds.RasterXSize,
        'rows': raster_ds.RasterYSize,
        'bands': raster_ds.RasterCount,
        'projection_wkt': raster_ds.GetProjection(),
        'geotransform': raster_ds.GetGeoTransform(),
        'srs': None
    }
    srs = osr.SpatialReference()
    info['srs'] = srs # Assign the object

    if info['projection_wkt']:
        try:
            srs.ImportFromWkt(info['projection_wkt'])
        except Exception:
            log_message(logger_queue, "Warning: Could not import SRS from WKT projection string.")
            info['projection_wkt'] = None

    if not info['projection_wkt'] and raster_ds.GetProjectionRef():
        proj_ref = raster_ds.GetProjectionRef()
        try:
            srs.ImportFromWkt(proj_ref)
            info['projection_wkt'] = proj_ref
        except Exception:
             log_message(logger_queue, "Warning: Could not import SRS from GetProjectionRef() string.")

    if not info['projection_wkt'] or not info['geotransform'] or info['geotransform'] == (0, 1, 0, 0, 0, 1):
        log_message(logger_queue, "Warning: Raster may lack a valid projection or geotransform. Results might be incorrect.")

    return info


def clear_and_repopulate_layer(layer, features_data, layer_name, action_desc="updating", logger_queue=None):
    """Clears all features from a layer and adds new ones. Handles transactions."""
    # ... (function remains the same as before) ...
    layer_defn = layer.GetLayerDefn()
    original_count = layer.GetFeatureCount()
    kept_count = len(features_data)

    if kept_count == 0 and original_count == 0:
        log_message(logger_queue, f"      Skipping rewrite for {action_desc}: layer '{layer_name}' is already empty.")
        return True

    log_message(logger_queue, f"      Repopulating layer '{layer_name}' for {action_desc}: Clearing {original_count} features, adding {kept_count} back...")

    deleted_count = 0
    try: # --- Clear Layer ---
        layer.StartTransaction()
        fids_to_delete = [feat.GetFID() for feat in layer] # Get all FIDs first
        layer.ResetReading() # Reset reading pointer
        for fid in fids_to_delete:
            err = layer.DeleteFeature(fid)
            if err == ogr.OGRERR_NONE:
                deleted_count += 1

        if deleted_count != original_count:
             log_message(logger_queue, f"        Warning: Deleted {deleted_count}/{original_count} features during clear operation.")

    except Exception as e:
        layer.RollbackTransaction() # Rollback on clear failure
        log_message(logger_queue, f"        Error clearing features in '{layer_name}': {e}")
        return False

    added_count = 0
    try: # --- Add Features Back ---
        for data in features_data:
            geom = data.get('geom')
            attrs = data.get('attributes', {})

            if geom is None or geom.IsEmpty():
                continue

            new_feature = ogr.Feature(layer_defn)
            # Important: Clone the geometry before setting, avoids ownership issues
            geom_clone = geom.Clone()
            if new_feature.SetGeometry(geom_clone) != ogr.OGRERR_NONE:
                 log_message(logger_queue, f"        Warning: Failed to set geometry during repopulation for feature with attrs: {attrs}. Skipping.")
                 if new_feature: new_feature.Destroy()
                 continue # Skip this feature

            for name, value in attrs.items():
                field_index = layer_defn.GetFieldIndex(name)
                if field_index >= 0:
                    try:
                        new_feature.SetField(name, value)
                    except Exception as set_field_e:
                         log_message(logger_queue, f"        Warning: Failed to set field '{name}' to '{value}' (type: {type(value)}): {set_field_e}")


            if layer.CreateFeature(new_feature) == ogr.OGRERR_NONE:
                added_count += 1
            else:
                 log_message(logger_queue, f"        Warning: Failed to create feature during repopulation for feature with attrs: {attrs}.")


            if new_feature:
                new_feature.Destroy()

        layer.CommitTransaction() # Commit combined delete & create

        if added_count != kept_count:
            log_message(logger_queue, f"        Warning: Added {added_count}/{kept_count} features during repopulation.")

    except Exception as e:
        layer.RollbackTransaction() # Rollback on add failure
        log_message(logger_queue, f"        Error adding features back to '{layer_name}': {e}")
        log_message(logger_queue, traceback.format_exc()) # More detail on error
        return False

    final_count = layer.GetFeatureCount()
    log_message(logger_queue, f"      Layer '{layer_name}' {action_desc} complete. Final feature count: {final_count} (Expected: {kept_count})")
    if final_count != kept_count:
         log_message(logger_queue, f"        Warning: Final count {final_count} does not match expected count {kept_count}!")

    return True


def simplify_layer(layer, tolerance, layer_name, logger_queue=None):
    """Simplifies geometries in a layer using SimplifyPreserveTopology."""
    # ... (function remains the same as before) ...
    action_desc = "simplification"
    start_time = time.time()
    if tolerance <= 0.0:
        log_message(logger_queue, f"    Skipping {action_desc} for '{layer_name}' (tolerance={tolerance}).")
        return True

    log_message(logger_queue, f"    Applying {action_desc} to layer '{layer_name}' (tolerance {tolerance} map units)...")
    feature_count = layer.GetFeatureCount()
    if feature_count == 0:
        log_message(logger_queue, f"    Layer '{layer_name}' is empty, skipping {action_desc}.")
        return True

    processed_features_data = []
    layer_defn = layer.GetLayerDefn()
    field_names = [layer_defn.GetFieldDefn(i).GetNameRef() for i in range(layer_defn.GetFieldCount())]

    layer.ResetReading()
    feature = layer.GetNextFeature()
    processed_count = 0
    log_message(logger_queue, f"      Simplifying {feature_count} features (updates every 5000)...")

    while feature:
        geom = feature.GetGeometryRef()
        attrs = {name: feature.GetField(name) for name in field_names}
        simplified_geom = None
        if geom:
            try:
                # Clone geometry before simplifying to avoid modifying original feature's geom
                geom_clone = geom.Clone()
                simplified = geom_clone.SimplifyPreserveTopology(tolerance)
                if simplified and not simplified.IsEmpty():
                    simplified_geom = simplified # Keep the simplified one
                else:
                    # Simplification resulted in empty geom, keep original (cloned)
                    simplified_geom = geom.Clone()
            except Exception as e:
                log_message(logger_queue, f"\n        Warning: SimplifyPreserveTopology failed for FID {feature.GetFID()}: {e}. Keeping original geometry.")
                simplified_geom = geom.Clone() # Keep original on error
        # No 'else' needed, simplified_geom remains None if original geom was None

        processed_features_data.append({'geom': simplified_geom, 'attributes': attrs})

        processed_count += 1
        if processed_count % 5000 == 0:
            elapsed = time.time() - start_time
            log_message(logger_queue, f"        Simplified {processed_count}/{feature_count} features in {elapsed:.1f}s...")

        if feature: feature.Destroy()
        feature = layer.GetNextFeature()

    success = clear_and_repopulate_layer(layer, processed_features_data, layer_name, action_desc, logger_queue)
    log_message(logger_queue, f"    Finished {action_desc} for '{layer_name}' in {time.time() - start_time:.2f}s.")
    return success


def filter_layer_by_min_area(layer, min_area, layer_name, logger_queue=None):
    """Filters features in a layer based on minimum geometry area."""
    # ... (function remains the same as before) ...
    action_desc = "minimum area filter"
    start_time = time.time()
    if min_area <= 0.0:
        log_message(logger_queue, f"    Skipping {action_desc} for '{layer_name}' (min_area={min_area}).")
        return True

    log_message(logger_queue, f"    Applying {action_desc} to layer '{layer_name}' (min_area {min_area} sq map units)...")
    feature_count = layer.GetFeatureCount()
    if feature_count == 0:
        log_message(logger_queue, f"    Layer '{layer_name}' is empty, skipping {action_desc}.")
        return True

    features_to_keep = []
    layer_defn = layer.GetLayerDefn()
    field_names = [layer_defn.GetFieldDefn(i).GetNameRef() for i in range(layer_defn.GetFieldCount())]

    layer.ResetReading()
    feature = layer.GetNextFeature()
    processed_count = 0
    removed_count = 0
    log_message(logger_queue, f"      Filtering {feature_count} features by area (updates every 5000)...")

    while feature:
        geom = feature.GetGeometryRef()
        area = 0.0
        keep = False
        if geom and not geom.IsEmpty():
            try:
                area = geom.Area()
                if area >= min_area:
                    keep = True
                else:
                     removed_count += 1
            except Exception as e:
                log_message(logger_queue, f"\n        Warning: Could not calculate area for FID {feature.GetFID()}: {e}. Feature will be removed by filter.")
                keep = False
                removed_count += 1
        else:
             removed_count +=1 # Remove features with null/empty geometry

        if keep:
            attrs = {name: feature.GetField(name) for name in field_names}
            features_to_keep.append({'geom': geom.Clone() if geom else None, 'attributes': attrs})

        processed_count += 1
        if processed_count % 5000 == 0:
            elapsed = time.time() - start_time
            log_message(logger_queue, f"        Area filter checked {processed_count}/{feature_count} features in {elapsed:.1f}s...")

        if feature: feature.Destroy()
        feature = layer.GetNextFeature()

    log_message(logger_queue, f"      Area filter complete. Removed {removed_count} features smaller than {min_area} sq units.")
    success = clear_and_repopulate_layer(layer, features_to_keep, layer_name, action_desc, logger_queue)
    log_message(logger_queue, f"    Finished {action_desc} for '{layer_name}' in {time.time() - start_time:.2f}s.")
    return success


# REMOVED: fill_small_holes function


def _apply_chaikin_to_ring(points, iterations, logger_queue=None):
    """Applies Chaikin's algorithm iteratively to a list of points (x, y tuples)."""
    # ... (function remains the same as before) ...
    if not points or len(points) < 4:
        return points

    current_points = list(points)

    for iter_num in range(iterations):
        new_points = []
        num_pts = len(current_points)
        if num_pts < 4: # Check inside loop too
             log_message(logger_queue, f"        Warning: Chaikin smoothing reduced points below minimum (4) at iteration {iter_num}. Stopping early.")
             break

        # Handle the segment connecting the last point back to the first
        p0 = current_points[num_pts - 2]
        p1 = current_points[0]

        q0_x = 0.75 * p0[0] + 0.25 * p1[0]
        q0_y = 0.75 * p0[1] + 0.25 * p1[1]
        q1_x = 0.25 * p0[0] + 0.75 * p1[0]
        q1_y = 0.25 * p0[1] + 0.75 * p1[1]

        last_q0 = (q0_x, q0_y)
        last_q1 = (q1_x, q1_y)

        for i in range(num_pts - 1):
            p0 = current_points[i]
            p1 = current_points[i+1]

            q0_x = 0.75 * p0[0] + 0.25 * p1[0]
            q0_y = 0.75 * p0[1] + 0.25 * p1[1]
            q1_x = 0.25 * p0[0] + 0.75 * p1[0]
            q1_y = 0.25 * p0[1] + 0.75 * p1[1]

            new_points.append((q0_x, q0_y))
            new_points.append((q1_x, q1_y))

        new_points.insert(0, last_q1)
        new_points.append(last_q0)

        if new_points:
            new_points.append(new_points[0]) # Close the ring

        current_points = new_points

    return current_points


def smooth_layer_chaikin(layer, iterations, layer_name, logger_queue=None):
    """Applies Chaikin's smoothing algorithm to Polygon/MultiPolygon features in a layer."""
    # ... (function remains the same as before) ...
    action_desc = f"Chaikin smoothing ({iterations} iterations)"
    start_time = time.time()

    log_message(logger_queue, f"    Applying {action_desc} to layer '{layer_name}'...")
    feature_count = layer.GetFeatureCount()
    if feature_count == 0:
        log_message(logger_queue, f"    Layer '{layer_name}' is empty, skipping {action_desc}.")
        return True

    processed_data = []
    layer_defn = layer.GetLayerDefn()
    field_names = [layer_defn.GetFieldDefn(i).GetNameRef() for i in range(layer_defn.GetFieldCount())]

    layer.ResetReading()
    feature = layer.GetNextFeature()
    processed_count = 0
    log_message(logger_queue, f"      Processing {feature_count} features for Chaikin smoothing (updates every 1000)...")

    while feature:
        geom = feature.GetGeometryRef()
        attrs = {name: feature.GetField(name) for name in field_names}
        processed_geom = None

        if geom and not geom.IsEmpty():
            geom_type = geom.GetGeometryType()
            # Ensure we only process Polygon/MultiPolygon
            flat_geom_type = ogr.GT_Flatten(geom_type) # Handle 2.5D types

            if flat_geom_type == ogr.wkbPolygon or flat_geom_type == ogr.wkbMultiPolygon:
                new_multi_poly = ogr.Geometry(ogr.wkbMultiPolygon)
                # Copy SRS from original geometry if it exists
                srs = geom.GetSpatialReference()
                if srs:
                    new_multi_poly.AssignSpatialReference(srs)

                num_parts = geom.GetGeometryCount() if flat_geom_type == ogr.wkbMultiPolygon else 1

                for k in range(num_parts):
                    part = geom.GetGeometryRef(k) if flat_geom_type == ogr.wkbMultiPolygon else geom

                    if not part or part.IsEmpty() or ogr.GT_Flatten(part.GetGeometryType()) != ogr.wkbPolygon:
                        continue

                    new_poly = ogr.Geometry(ogr.wkbPolygon)
                    if srs: new_poly.AssignSpatialReference(srs)
                    num_rings = part.GetGeometryCount()

                    for i in range(num_rings):
                        ring = part.GetGeometryRef(i)
                        if not ring or ring.IsEmpty() or ogr.GT_Flatten(ring.GetGeometryType()) != ogr.wkbLinearRing:
                            continue

                        points = ring.GetPoints() # Gets (x, y) or (x, y, z)
                        if not points or len(points) < 4: # Need at least 4 points for a valid ring
                             new_poly.AddGeometry(ring.Clone()) # Keep original ring if too few points
                             continue

                        try:
                            # _apply_chaikin_to_ring works on (x,y) tuples. Extract if needed.
                            points_2d = [(p[0], p[1]) for p in points]
                            smoothed_points_2d = _apply_chaikin_to_ring(points_2d, iterations, logger_queue)

                            if smoothed_points_2d and len(smoothed_points_2d) >= 4:
                                new_ring = ogr.Geometry(ogr.wkbLinearRing)
                                if srs: new_ring.AssignSpatialReference(srs)
                                # Re-apply Z if original had it (using average Z or first point Z?)
                                has_z = len(points[0]) > 2
                                z_val = points[0][2] if has_z else 0.0 # Simple approach: use first Z

                                for pt in smoothed_points_2d:
                                    if has_z:
                                        new_ring.AddPoint(pt[0], pt[1], z_val)
                                    else:
                                        new_ring.AddPoint(pt[0], pt[1])

                                # Check if ring is valid after smoothing (can become self-intersecting)
                                if new_ring.IsValid():
                                     new_poly.AddGeometry(new_ring)
                                else:
                                     log_message(logger_queue, f"        Warning: Chaikin resulted in invalid ring geom for FID {feature.GetFID()}, part {k}, ring {i}. Using original ring.")
                                     new_poly.AddGeometry(ring.Clone())

                            else: # Smoothing failed or resulted in too few points
                                new_poly.AddGeometry(ring.Clone())

                        except Exception as e:
                            log_message(logger_queue, f"\n        Error during Chaikin smoothing for FID {feature.GetFID()}, part {k}, ring {i}: {e}. Using original ring.")
                            new_poly.AddGeometry(ring.Clone())


                    if not new_poly.IsEmpty():
                         # Check validity of the constructed polygon before adding to multipolygon
                         if new_poly.IsValid():
                             err = new_multi_poly.AddGeometry(new_poly)
                             if err != ogr.OGRERR_NONE:
                                 log_message(logger_queue, f"        Warning: Failed to add smoothed polygon part {k} for FID {feature.GetFID()} to MultiPolygon. Error: {err}")
                         else:
                              log_message(logger_queue, f"        Warning: Polygon part {k} invalid after smoothing rings for FID {feature.GetFID()}. Skipping this part.")

                # After processing all parts, assign the result
                if not new_multi_poly.IsEmpty():
                    # Ensure final MultiPolygon is valid
                    if not new_multi_poly.IsValid():
                         log_message(logger_queue, f"        Warning: Final MultiPolygon for FID {feature.GetFID()} is invalid after smoothing. Attempting MakeValid.")
                         repaired_multi = new_multi_poly.MakeValid()
                         if repaired_multi and not repaired_multi.IsEmpty() and repaired_multi.IsValid():
                              processed_geom = repaired_multi.Clone()
                         else:
                              log_message(logger_queue, f"          MakeValid failed for smoothed MultiPolygon FID {feature.GetFID()}. Keeping original.")
                              processed_geom = geom.Clone() # Keep original if repair fails
                    else:
                         processed_geom = new_multi_poly.Clone()
                else: # Result is empty
                    processed_geom = geom.Clone() # Keep original if result is empty

            else: # Keep non-polygon geometries as they are
                processed_geom = geom.Clone()
        else: # Handle null/empty input
            processed_geom = None

        processed_data.append({'geom': processed_geom, 'attributes': attrs})

        processed_count += 1
        if processed_count % 1000 == 0: # Update less frequently for smoothing
            elapsed = time.time() - start_time
            log_message(logger_queue, f"        Smoothed {processed_count}/{feature_count} features in {elapsed:.1f}s...")

        if feature: feature.Destroy()
        feature = layer.GetNextFeature()

    success = clear_and_repopulate_layer(layer, processed_data, layer_name, action_desc, logger_queue)
    log_message(logger_queue, f"    Finished {action_desc} for '{layer_name}' in {time.time() - start_time:.2f}s.")
    return success


# --- NEW: Function to Fix Geometries ---
def fix_layer_geometries(layer, layer_name, logger_queue=None):
    """
    Checks for invalid geometries, attempts repair using MakeValid(),
    and ensures only valid geometries of the layer's type remain.
    Handles GeometryCollections resulting from MakeValid for Polygon layers.
    """
    action_desc = "geometry fixing"
    start_time = time.time()
    log_message(logger_queue, f"    Applying {action_desc} to layer '{layer_name}'...")
    feature_count = layer.GetFeatureCount()
    if feature_count == 0:
        log_message(logger_queue, f"    Layer '{layer_name}' is empty, skipping {action_desc}.")
        return True

    layer_defn = layer.GetLayerDefn()
    field_names = [layer_defn.GetFieldDefn(i).GetNameRef() for i in range(layer_defn.GetFieldCount())]
    target_geom_type = layer.GetGeomType() # Get the layer's geometry type (e.g., wkbMultiPolygon)
    target_flat_geom_type = ogr.GT_Flatten(target_geom_type) # Base type (e.g., wkbPolygon)

    processed_data = []
    invalid_count = 0
    repaired_count = 0
    discarded_count = 0

    layer.ResetReading()
    feature = layer.GetNextFeature()
    processed_count = 0
    log_message(logger_queue, f"      Checking/Fixing {feature_count} geometries (updates every 5000)...")

    while feature:
        processed_count += 1
        geom = feature.GetGeometryRef()
        attrs = {name: feature.GetField(name) for name in field_names}
        fid = feature.GetFID()
        final_geom = None # Geometry to keep for this feature

        if geom and not geom.IsEmpty():
            if geom.IsValid():
                final_geom = geom.Clone() # Keep valid geometry
            else:
                invalid_count += 1
                # Attempt repair
                try:
                    repaired_geom = geom.MakeValid()
                except Exception as make_valid_err:
                     log_message(logger_queue, f"        Warning: MakeValid() crashed for FID {fid}: {make_valid_err}. Discarding feature.")
                     repaired_geom = None
                     discarded_count +=1


                if repaired_geom and not repaired_geom.IsEmpty():
                    repaired_type = repaired_geom.GetGeometryType()
                    repaired_flat_type = ogr.GT_Flatten(repaired_type)

                    # --- Handle Repair Results ---
                    # Case 1: Repaired type matches target layer type (or its base type)
                    if repaired_flat_type == target_flat_geom_type:
                        if repaired_geom.IsValid(): # Double check validity after repair
                            final_geom = repaired_geom.Clone()
                            repaired_count += 1
                        else:
                             log_message(logger_queue, f"        Warning: MakeValid() produced an invalid geometry of type {ogr.GeometryTypeToName(repaired_type)} for FID {fid}. Discarding feature.")
                             discarded_count += 1
                    # Case 2: Repaired to GeometryCollection (Common for invalid polygons)
                    elif repaired_flat_type == ogr.wkbGeometryCollection and \
                         (target_flat_geom_type == ogr.wkbPolygon or target_flat_geom_type == ogr.wkbMultiPolygon):
                        # Extract valid polygons from the collection
                        collection_extract = ogr.Geometry(target_geom_type) # Create container (e.g., MultiPolygon)
                        srs = geom.GetSpatialReference()
                        if srs: collection_extract.AssignSpatialReference(srs)
                        valid_parts_found = False
                        for i in range(repaired_geom.GetGeometryCount()):
                            part = repaired_geom.GetGeometryRef(i)
                            if part and not part.IsEmpty() and ogr.GT_Flatten(part.GetGeometryType()) == ogr.wkbPolygon and part.IsValid():
                                err = collection_extract.AddGeometry(part.Clone())
                                if err == ogr.OGRERR_NONE:
                                     valid_parts_found = True
                                else:
                                     log_message(logger_queue, f"        Warning: Failed to add valid polygon part from GeometryCollection for FID {fid}. Error: {err}")


                        if valid_parts_found:
                             # Ensure the final collection is valid itself
                             if collection_extract.IsValid():
                                 final_geom = collection_extract # Keep the extracted polygons
                                 repaired_count += 1
                                 log_message(logger_queue, f"        Info: Repaired FID {fid} to GeometryCollection, extracted valid {ogr.GeometryTypeToName(target_geom_type)}.")
                             else:
                                 log_message(logger_queue, f"        Warning: Extracted geometry from GeometryCollection for FID {fid} is invalid. Discarding feature.")
                                 discarded_count += 1
                        else:
                            log_message(logger_queue, f"        Warning: MakeValid() produced GeometryCollection for FID {fid}, but no valid {ogr.GeometryTypeToName(target_geom_type)} parts found. Discarding feature.")
                            discarded_count += 1
                    # Case 3: Repaired to something completely different (e.g., Point/Line for a Polygon layer)
                    else:
                        log_message(logger_queue, f"        Warning: MakeValid() repaired FID {fid} to an incompatible type ({ogr.GeometryTypeToName(repaired_type)} for target {ogr.GeometryTypeToName(target_geom_type)}). Discarding feature.")
                        discarded_count += 1
                else:
                     # MakeValid failed or produced empty geometry
                     log_message(logger_queue, f"        Warning: MakeValid() failed or produced empty geometry for FID {fid}. Discarding feature.")
                     discarded_count += 1
        else:
            # Original geometry was null/empty, discard
            discarded_count += 1


        # Only add feature back if we have a valid final geometry
        if final_geom:
            processed_data.append({'geom': final_geom, 'attributes': attrs})

        # Progress update
        if processed_count % 5000 == 0:
            elapsed = time.time() - start_time
            log_message(logger_queue, f"        Checked/Fixed {processed_count}/{feature_count} geometries in {elapsed:.1f}s...")

        if feature: feature.Destroy()
        feature = layer.GetNextFeature()

    log_message(logger_queue, f"      Geometry fixing complete. Found {invalid_count} invalid, repaired {repaired_count}, discarded {discarded_count}.")
    success = clear_and_repopulate_layer(layer, processed_data, layer_name, action_desc, logger_queue)
    log_message(logger_queue, f"    Finished {action_desc} for '{layer_name}' in {time.time() - start_time:.2f}s.")
    return success


def filter_layer_by_dn(layer, keep_dn_value, layer_name, logger_queue=None):
    """Filters features based on the 'DN' field value."""
    # ... (function remains the same as before) ...
    action_desc = f"DN filter (keep DN={keep_dn_value})"
    start_time = time.time()
    log_message(logger_queue, f"    Applying {action_desc} to layer '{layer_name}'...")
    feature_count = layer.GetFeatureCount()
    if feature_count == 0:
        log_message(logger_queue, f"    Layer '{layer_name}' is empty, skipping {action_desc}.")
        return True

    features_to_keep = []
    layer_defn = layer.GetLayerDefn()
    dn_idx = layer_defn.GetFieldIndex('DN')
    if dn_idx < 0:
        log_message(logger_queue, f"      Error: Field 'DN' not found in layer '{layer_name}'. Cannot filter.")
        return False

    field_names = [layer_defn.GetFieldDefn(i).GetNameRef() for i in range(layer_defn.GetFieldCount())]

    layer.ResetReading()
    feature = layer.GetNextFeature()
    processed_count = 0
    kept_count = 0
    log_message(logger_queue, f"      Filtering {feature_count} features by DN (updates every 5000)...")

    while feature:
        try:
            dn = feature.GetField(dn_idx)
            if dn == keep_dn_value:
                geom = feature.GetGeometryRef()
                 # Only keep features with valid geometry after potential fixing
                if geom and not geom.IsEmpty() and geom.IsValid():
                    attrs = {name: feature.GetField(name) for name in field_names}
                    features_to_keep.append({'geom': geom.Clone() if geom else None, 'attributes': attrs})
                    kept_count += 1
                # else: # Feature might have been removed by geometry fixing if DN filter is last
                #     log_message(logger_queue, f"        Skipping FID {feature.GetFID()} in DN filter due to invalid/empty geometry.")

        except Exception as e:
            log_message(logger_queue, f"\n        Warning: Error reading DN field for FID {feature.GetFID()}: {e}. Skipping feature.")

        processed_count += 1
        if processed_count % 5000 == 0:
            elapsed = time.time() - start_time
            log_message(logger_queue, f"        DN filter checked {processed_count}/{feature_count} features in {elapsed:.1f}s...")

        if feature: feature.Destroy()
        feature = layer.GetNextFeature()

    if kept_count == feature_count and feature_count > 0:
        log_message(logger_queue, f"      Skipping rewrite for {action_desc}: all {feature_count} features met criteria.")
        return True

    success = clear_and_repopulate_layer(layer, features_to_keep, layer_name, action_desc, logger_queue)
    log_message(logger_queue, f"    Finished {action_desc} for '{layer_name}' in {time.time() - start_time:.2f}s.")
    return success


def initial_polygonize_band(raster_ds, band_num, threshold_255, out_layer, layer_name, logger_queue=None, progress_callback=None):
    """Polygonizes a raster band based on a threshold value."""
    # ... (function remains the same as before) ...
    log_message(logger_queue, f"\n--- Initial Polygonization: Band {band_num} ({layer_name}) ---")
    start_time = time.time()

    if band_num <= 0 or band_num > raster_ds.RasterCount:
        log_message(logger_queue, f"Error: Band number {band_num} is invalid for this raster (1 to {raster_ds.RasterCount}).")
        return False

    band = raster_ds.GetRasterBand(band_num)
    if not band:
        log_message(logger_queue, f"Error: Could not get Band {band_num} from the raster.")
        return False

    log_message(logger_queue, f"  Reading band {band_num} data...")
    try:
        band_array = band.ReadAsArray()
        if band_array is None:
            raise MemoryError(f"ReadAsArray returned None for band {band_num}. Check memory or GDAL limits.")
    except (MemoryError, Exception) as e:
        log_message(logger_queue, f"Error reading band {band_num}: {e}")
        log_message(logger_queue, "Consider tiling or using a machine with more RAM for very large rasters.")
        return False

    # --- Thresholding ---
    threshold_value = int(threshold_255) # Ensure it's an integer for comparison
    # Using explicit confidence naming here
    log_message(logger_queue, f"  Applying confidence threshold >= {threshold_value} ({threshold_value/255.0*100:.1f}%)...")
    thresholded_array = (band_array >= threshold_value).astype(np.uint8)
    band_array = None # Free memory
    pixels_above = np.sum(thresholded_array)

    if pixels_above == 0:
        log_message(logger_queue, f"  Warning: No pixels meet the confidence threshold >= {threshold_value}. Layer '{layer_name}' will be empty.")
        return True
    else:
        log_message(logger_queue, f"  Found {pixels_above} pixels >= confidence threshold.")

    # --- In-Memory Raster for Polygonize ---
    log_message(logger_queue, "  Creating temporary thresholded raster in memory...")
    mem_driver = gdal.GetDriverByName('MEM')
    temp_ds = None
    try:
        temp_ds = mem_driver.Create('', raster_ds.RasterXSize, raster_ds.RasterYSize, 1, gdal.GDT_Byte)
        if not temp_ds:
            raise RuntimeError("Failed to create in-memory raster dataset.")
        temp_ds.SetGeoTransform(raster_ds.GetGeoTransform())
        temp_ds.SetProjection(raster_ds.GetProjection())
        temp_band = temp_ds.GetRasterBand(1)
        temp_band.WriteArray(thresholded_array)
        thresholded_array = None # Free memory
        temp_band.FlushCache()
        temp_band.SetNoDataValue(0)

    except Exception as e:
        log_message(logger_queue, f"Error setting up temporary in-memory raster: {e}")
        if temp_ds: temp_ds = None # Ensure cleanup
        temp_band = None
        return False

    # --- Polygonize ---
    log_message(logger_queue, "  Polygonizing (using 8-connectedness)...")
    dn_field_index = out_layer.GetLayerDefn().GetFieldIndex('DN')
    if dn_field_index < 0:
        log_message(logger_queue, "Error: 'DN' field not found in the output layer before polygonization.")
        if temp_ds: temp_ds = None; temp_band = None
        return False

    poly_opts = ['8CONNECTED=YES']
    result = gdal.Polygonize(temp_band, None, out_layer, dn_field_index, poly_opts, callback=progress_callback)

    if temp_ds: temp_ds = None # Release memory raster
    temp_band = None

    if result != 0:
        # Attempt to get more specific error message if available
        err_msg = gdal.GetLastErrorMsg()
        if not err_msg or "unknown" in err_msg.lower():
             err_msg = f"Polygonize failed with error code {result}."
        log_message(logger_queue, f"Error during gdal.Polygonize: {err_msg}")
        log_message(logger_queue, f"  Layer '{layer_name}' feature count after failed polygonization: {out_layer.GetFeatureCount()}")
        return False
    else:
        log_message(logger_queue, f"  Polygonization created {out_layer.GetFeatureCount()} features initially in '{layer_name}'.")

    log_message(logger_queue, f"--- Initial Polygonization for '{layer_name}' finished in {time.time() - start_time:.2f}s ---")
    return True


# --- Core Processing Function (Called by GUI Thread) ---
def run_processing(params, logger_queue):
    """
    Main processing logic, adapted from the original main() function.
    Takes parameters dictionary and a queue for logging.
    """
    log_message(logger_queue, "--- Starting Raster Vectorization ---")

    # Unpack parameters
    input_raster_path = params['input_raster']
    output_dir = params['output_dir']
    output_name = params['output_name']
    force_overwrite = params['force']
    # Updated naming
    confidence_threshold_bldg_pct = params['conf_thresh_bldg_pct'] # GUI Var name change
    simplify_tolerance_buildings = params['simplify_bldg']
    min_area_buildings = params['min_area_bldg']
    # REMOVED: max_hole_area_buildings
    confidence_threshold_road_pct = params['conf_thresh_road_pct'] # GUI Var name change
    simplify_tolerance_roads = params['simplify_road']
    min_area_roads = params['min_area_road']
    chaikin_iterations_roads = params['smooth_roads_chaikin']

    # Derived parameters
    threshold_255_buildings = max(0, min(255, int(confidence_threshold_bldg_pct / 100.0 * 255)))
    threshold_255_roads = max(0, min(255, int(confidence_threshold_road_pct / 100.0 * 255)))

    log_message(logger_queue, "\nParameters:")
    log_message(logger_queue, f"  Input Raster: {input_raster_path}")
    log_message(logger_queue, f"  Output Directory: {output_dir}")
    log_message(logger_queue, f"  Output Filename: {output_name}")
    log_message(logger_queue, f"  Overwrite Existing: {'Yes' if force_overwrite else 'No'}")
    log_message(logger_queue, f"  Building Settings:")
    # Updated logging terminology
    log_message(logger_queue, f"    Confidence Threshold: {confidence_threshold_bldg_pct:.1f}% ({threshold_255_buildings}/255)")
    log_message(logger_queue, f"    Simplify Tolerance: {simplify_tolerance_buildings} map units")
    log_message(logger_queue, f"    Min Area: {min_area_buildings} sq map units")
    # REMOVED: Max Hole Area log
    log_message(logger_queue, f"  Road Settings:")
    # Updated logging terminology
    log_message(logger_queue, f"    Confidence Threshold: {confidence_threshold_road_pct:.1f}% ({threshold_255_roads}/255)")
    log_message(logger_queue, f"    Simplify Tolerance: {simplify_tolerance_roads} map units")
    log_message(logger_queue, f"    Min Area: {min_area_roads} sq map units")
    smoothing_status = f"Enabled ({chaikin_iterations_roads} iterations)" if chaikin_iterations_roads > 0 else "Disabled"
    log_message(logger_queue, f"    Chaikin Smoothing: {smoothing_status}")
    log_message(logger_queue, "-" * 20)

    # --- Prepare Output Path & Overwrite Handling ---
    # ... (remains the same) ...
    if not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir, exist_ok=True)
            log_message(logger_queue, f"Created output directory: {output_dir}")
        except OSError as e:
            log_message(logger_queue, f"Error: Could not create output directory '{output_dir}': {e}")
            logger_queue.put("PROCESS_COMPLETE_FAILURE") # Signal failure
            return False # Indicate failure

    output_gpkg_path = os.path.join(output_dir, output_name)

    if os.path.exists(output_gpkg_path):
        if force_overwrite:
            log_message(logger_queue, f"Output file '{output_gpkg_path}' exists. Overwriting...")
            try:
                driver = ogr.GetDriverByName("GPKG")
                if driver:
                    test_ds = None
                    try:
                        test_ds = driver.Open(output_gpkg_path, 0)
                    except: pass
                    finally:
                       if test_ds: test_ds = None

                    try:
                       delete_success = driver.DeleteDataSource(output_gpkg_path)
                       if delete_success != ogr.OGRERR_NONE:
                             # Sometimes DeleteDataSource returns non-zero even on success?
                             # Try os.remove as fallback
                             if os.path.exists(output_gpkg_path):
                                 log_message(logger_queue, f"  GDAL driver DeleteDataSource indicated non-success ({delete_success}). Attempting os.remove...")
                                 os.remove(output_gpkg_path)
                                 log_message(logger_queue, f"  Successfully deleted existing file using os.remove.")
                             else:
                                 log_message(logger_queue, f"  Successfully deleted existing file using GDAL driver (despite non-zero return).")

                       else:
                            log_message(logger_queue, f"  Successfully deleted existing file using GDAL driver.")
                    except Exception as gdal_del_e:
                         log_message(logger_queue, f"  GDAL driver failed to delete ({gdal_del_e}). Attempting os.remove...")
                         try:
                             os.remove(output_gpkg_path)
                             log_message(logger_queue, f"  Successfully deleted existing file using os.remove.")
                         except Exception as os_del_e:
                             raise RuntimeError(f"Both GDAL and os.remove failed to delete '{output_gpkg_path}': {gdal_del_e} / {os_del_e}")

                else:
                    log_message(logger_queue, f"  GPKG driver not found. Attempting os.remove...")
                    os.remove(output_gpkg_path)
                    log_message(logger_queue, f"  Successfully deleted existing file using os.remove.")
            except Exception as e:
                log_message(logger_queue, f"Error: Could not remove existing output file '{output_gpkg_path}': {e}")
                logger_queue.put("PROCESS_COMPLETE_FAILURE")
                return False
        else:
            log_message(logger_queue, f"\nError: Output file exists: '{output_gpkg_path}'. Enable 'Force Overwrite' checkbox.")
            logger_queue.put("PROCESS_COMPLETE_FAILURE")
            return False


    # --- Open Input Raster ---
    # ... (remains the same) ...
    log_message(logger_queue, f"\nOpening raster: {input_raster_path}")
    raster_ds = None
    try:
        raster_ds = gdal.Open(input_raster_path, gdal.GA_ReadOnly)
        if raster_ds is None:
            raise RuntimeError(f"Could not open raster file. Check path and format.")

        raster_info = get_raster_info(raster_ds, logger_queue)
        if not raster_info:
            raise RuntimeError("Error getting raster metadata.")

        if raster_info['bands'] < 2:
            raise RuntimeError(f"Input raster needs at least 2 bands (Roads=1, Buildings=2). Found: {raster_info['bands']}")

        log_message(logger_queue, f"Raster Info: {raster_info['cols']}x{raster_info['rows']}, {raster_info['bands']} bands.")
        if not raster_info['srs'] or not raster_info['srs'].IsProjected():
             log_message(logger_queue, "Warning: Input raster SRS is missing, invalid, or geographic.")
             log_message(logger_queue, "  Area/Simplification units assumed meters; results may be incorrect.")
             log_message(logger_queue, "  Consider reprojecting input to a projected CRS (e.g., UTM) first.")

    except Exception as e:
        log_message(logger_queue, f"Error opening or validating raster: {e}")
        if raster_ds: raster_ds = None
        logger_queue.put("PROCESS_COMPLETE_FAILURE")
        return False

    # --- Create Output GeoPackage & Process ---
    # ... (remains the same, GPKG driver check etc) ...
    log_message(logger_queue, f"\nCreating output GeoPackage: {output_gpkg_path}")
    gpkg_driver = ogr.GetDriverByName('GPKG')
    if not gpkg_driver:
        log_message(logger_queue, "Error: GPKG driver not available in this GDAL installation.")
        if raster_ds: raster_ds = None
        logger_queue.put("PROCESS_COMPLETE_FAILURE")
        return False


    out_ds = None
    success_roads = False
    success_buildings = False
    roads_layer_name = "roads_vector"
    buildings_layer_name = "buildings_vector"

    try:
        out_ds = gpkg_driver.CreateDataSource(output_gpkg_path)
        if out_ds is None:
            raise ogr.OGRError(f"Could not create GeoPackage datasource: {output_gpkg_path}")

        dn_field = ogr.FieldDefn('DN', ogr.OFTInteger)

        # === Process Roads (Band 1) ===
        log_message(logger_queue, f"\n===== PROCESSING ROADS (Band 1) =====")
        roads_layer = out_ds.CreateLayer(roads_layer_name, srs=raster_info['srs'], geom_type=ogr.wkbMultiPolygon)
        if not roads_layer:
            raise ogr.OGRError(f"Failed to create layer: '{roads_layer_name}'")
        roads_layer.CreateField(dn_field)

        poly_ok_roads = initial_polygonize_band(raster_ds, 1, threshold_255_roads, roads_layer, roads_layer_name, logger_queue)

        if poly_ok_roads and roads_layer.GetFeatureCount() > 0:
            log_message(logger_queue, f"\n--- Post-processing Roads Layer '{roads_layer_name}' ---")
            # Pipeline: Simplify -> Filter Area -> Fix Geometry -> Smooth -> Filter DN
            simp_ok = simplify_layer(roads_layer, simplify_tolerance_roads, roads_layer_name, logger_queue)
            area_ok = filter_layer_by_min_area(roads_layer, min_area_roads, roads_layer_name, logger_queue) if simp_ok else False
            # --- Add Geometry Fixing ---
            fix_geom_ok = fix_layer_geometries(roads_layer, roads_layer_name, logger_queue) if simp_ok and area_ok else False
            # ---------------------------

            smooth_ok = True
            if chaikin_iterations_roads > 0:
                # Only smooth if previous steps were successful
                if simp_ok and area_ok and fix_geom_ok:
                    smooth_ok = smooth_layer_chaikin(roads_layer, chaikin_iterations_roads, roads_layer_name, logger_queue)
                else:
                    smooth_ok = False
                    log_message(logger_queue, "Skipping road Chaikin smoothing due to prior processing errors.")
            else:
                 log_message(logger_queue, f"    Skipping Chaikin smoothing for '{roads_layer_name}' (iterations=0).")

            # Run DN filter only if all previous steps succeeded
            dn_ok_final = filter_layer_by_dn(roads_layer, 1, roads_layer_name, logger_queue) if simp_ok and area_ok and fix_geom_ok and smooth_ok else False
            # Update overall success check for roads
            success_roads = simp_ok and area_ok and fix_geom_ok and smooth_ok and dn_ok_final

        elif poly_ok_roads: # Polygonization succeeded but layer is empty
            log_message(logger_queue, f"Skipping road post-processing: layer '{roads_layer_name}' is empty.")
            success_roads = True # Considered successful if layer is correctly empty
        else: # Polygonization failed
            log_message(logger_queue, f"Skipping road post-processing due to polygonization failure for '{roads_layer_name}'.")
            success_roads = False
        roads_layer = None # Release layer

        # === Process Buildings (Band 2) ===
        log_message(logger_queue, f"\n===== PROCESSING BUILDINGS (Band 2) =====")
        buildings_layer = out_ds.CreateLayer(buildings_layer_name, srs=raster_info['srs'], geom_type=ogr.wkbMultiPolygon)
        if not buildings_layer:
            raise ogr.OGRError(f"Failed to create layer: '{buildings_layer_name}'")
        buildings_layer.CreateField(dn_field)

        poly_ok_buildings = initial_polygonize_band(raster_ds, 2, threshold_255_buildings, buildings_layer, buildings_layer_name, logger_queue)

        if poly_ok_buildings and buildings_layer.GetFeatureCount() > 0:
            log_message(logger_queue, f"\n--- Post-processing Buildings Layer '{buildings_layer_name}' ---")
            # Pipeline: Simplify -> Filter Area -> Fix Geometry -> Filter DN
            simp_ok = simplify_layer(buildings_layer, simplify_tolerance_buildings, buildings_layer_name, logger_queue)
            area_ok = filter_layer_by_min_area(buildings_layer, min_area_buildings, buildings_layer_name, logger_queue) if simp_ok else False
            # REMOVED: hole_ok = fill_small_holes(...)
            # --- Add Geometry Fixing ---
            fix_geom_ok = fix_layer_geometries(buildings_layer, buildings_layer_name, logger_queue) if simp_ok and area_ok else False
            # ---------------------------
            dn_ok = filter_layer_by_dn(buildings_layer, 1, buildings_layer_name, logger_queue) if simp_ok and area_ok and fix_geom_ok else False

            success_buildings = simp_ok and area_ok and fix_geom_ok and dn_ok # Updated success check
        elif poly_ok_buildings: # Polygonization succeeded but layer is empty
            log_message(logger_queue, f"Skipping building post-processing: layer '{buildings_layer_name}' is empty.")
            success_buildings = True # Considered successful
        else: # Polygonization failed
            log_message(logger_queue, f"Skipping building post-processing due to polygonization failure for '{buildings_layer_name}'.")
            success_buildings = False
        buildings_layer = None # Release layer

    except Exception as e:
        log_message(logger_queue, f"\nAn critical error occurred during processing: {e}")
        log_message(logger_queue, traceback.format_exc())
        success_roads = False
        success_buildings = False
        # No return here, let finally block run, but signal failure via queue

    finally: # Cleanup
        log_message(logger_queue, "\nCleaning up resources...")
        if out_ds is not None:
            try:
                # Force layer objects to be released before closing DS if they weren't set to None
                if 'roads_layer' in locals() and roads_layer is not None: roads_layer = None
                if 'buildings_layer' in locals() and buildings_layer is not None: buildings_layer = None
                out_ds.FlushCache()
                out_ds = None
                log_message(logger_queue, "  Output GeoPackage closed.")
            except Exception as e_close:
                log_message(logger_queue, f"  Warning: Error closing output GeoPackage: {e_close}")
        if raster_ds is not None:
            raster_ds = None
            log_message(logger_queue, "  Input raster closed.")
        log_message(logger_queue, "Resource cleanup finished.")

    # --- Final Status ---
    log_message(logger_queue, "\n===== PROCESSING SUMMARY =====")
    log_message(logger_queue, f"Roads processing successful: {success_roads}")
    log_message(logger_queue, f"Buildings processing successful: {success_buildings}")

    overall_success = success_roads and success_buildings

    if overall_success:
        log_message(logger_queue, f"\nProcessing complete. Output saved to: {output_gpkg_path}")
        try:
            final_ds = ogr.Open(output_gpkg_path, 0)
            if final_ds:
                final_roads_layer = final_ds.GetLayerByName(roads_layer_name)
                final_bldg_layer = final_ds.GetLayerByName(buildings_layer_name)
                log_message(logger_queue, f"Final feature counts:")
                log_message(logger_queue, f"  Layer '{roads_layer_name}': {final_roads_layer.GetFeatureCount() if final_roads_layer else 'Not Found'}")
                log_message(logger_queue, f"  Layer '{buildings_layer_name}': {final_bldg_layer.GetFeatureCount() if final_bldg_layer else 'Not Found'}")
                final_ds = None
            else:
                log_message(logger_queue, "Could not reopen final GeoPackage to verify feature counts.")
        except Exception as e:
            log_message(logger_queue, f"Error verifying final feature counts: {e}")
        logger_queue.put("PROCESS_COMPLETE_SUCCESS")

    else:
        log_message(logger_queue, "\nProcessing finished, but one or more stages failed or encountered errors.")
        log_message(logger_queue, f"Output file '{output_gpkg_path}' may be incomplete or contain errors.")
        logger_queue.put("PROCESS_COMPLETE_FAILURE")

    # This return value isn't currently used by the GUI thread, but good practice
    return overall_success


# --- Tkinter GUI Application ---

class VectorizationApp:
    def __init__(self, master):
        self.master = master
        master.title("Raster Vectorization Tool")
        # master.geometry("750x700") # Optional: set initial size

        # --- Style ---
        self.style = ttk.Style()
        # Try different themes for better appearance on various OS
        available_themes = self.style.theme_names()
        # Prefer 'clam', 'alt', or 'default' generally
        if 'clam' in available_themes:
            self.style.theme_use('clam')
        elif 'alt' in available_themes:
            self.style.theme_use('alt')
        elif 'vista' in available_themes: # Good on Windows
             self.style.theme_use('vista')
        elif 'aqua' in available_themes: # Good on Mac
             self.style.theme_use('aqua')
        else:
             self.style.theme_use(available_themes[0]) # Fallback


        # --- Variables ---
        self.input_raster_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.output_name_var = tk.StringVar(value=DEFAULT_OUTPUT_NAME)
        self.force_overwrite_var = tk.BooleanVar(value=False)

        # Updated naming and defaults
        self.conf_thresh_bldg_var = tk.DoubleVar(value=DEFAULT_CONFIDENCE_THRESHOLD_BUILDING)
        self.simplify_bldg_var = tk.DoubleVar(value=DEFAULT_SIMPLIFY_BUILDING)
        self.min_area_bldg_var = tk.DoubleVar(value=DEFAULT_MIN_AREA_BUILDING)
        # REMOVED: max_hole_bldg_var

        self.conf_thresh_road_var = tk.DoubleVar(value=DEFAULT_CONFIDENCE_THRESHOLD_ROAD)
        self.simplify_road_var = tk.DoubleVar(value=DEFAULT_SIMPLIFY_ROAD)
        self.min_area_road_var = tk.DoubleVar(value=DEFAULT_MIN_AREA_ROAD)
        self.smooth_roads_chaikin_var = tk.IntVar(value=DEFAULT_CHAIKIN_ITERATIONS_ROAD)

        # For displaying slider values
        self.conf_thresh_bldg_display_var = tk.StringVar(value=f"{self.conf_thresh_bldg_var.get():.1f}%")
        self.conf_thresh_road_display_var = tk.StringVar(value=f"{self.conf_thresh_road_var.get():.1f}%")

        # Queue for log messages from the processing thread
        self.log_queue = queue.Queue()

        # --- GUI Layout ---
        main_frame = ttk.Frame(master, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)

        # Configure main_frame grid weights
        main_frame.columnconfigure(1, weight=1) # Allow entry fields/paths to expand
        main_frame.rowconfigure(3, weight=1) # Allow log area to expand

        # --- Input/Output Frame ---
        io_frame = ttk.LabelFrame(main_frame, text="Input / Output", padding="10")
        io_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        io_frame.columnconfigure(1, weight=1)

        ttk.Label(io_frame, text="Input Raster:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.input_entry = ttk.Entry(io_frame, textvariable=self.input_raster_var, width=60)
        self.input_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.browse_input_button = ttk.Button(io_frame, text="Browse...", command=self.browse_input)
        self.browse_input_button.grid(row=0, column=2, sticky=tk.E, padx=5, pady=2)

        ttk.Label(io_frame, text="Output Directory:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.output_dir_entry = ttk.Entry(io_frame, textvariable=self.output_dir_var, width=60)
        self.output_dir_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.browse_output_dir_button = ttk.Button(io_frame, text="Browse...", command=self.browse_output_dir)
        self.browse_output_dir_button.grid(row=1, column=2, sticky=tk.E, padx=5, pady=2)

        ttk.Label(io_frame, text="Output Filename:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.output_name_entry = ttk.Entry(io_frame, textvariable=self.output_name_var, width=30)
        self.output_name_entry.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2) # Align left

        self.force_check = ttk.Checkbutton(io_frame, text="Force Overwrite", variable=self.force_overwrite_var)
        self.force_check.grid(row=3, column=1, sticky=tk.W, padx=5, pady=5)

        # --- Settings Frames ---
        settings_frame = ttk.Frame(main_frame)
        settings_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        settings_frame.columnconfigure(0, weight=1)
        settings_frame.columnconfigure(1, weight=1)

        # Buildings Frame
        bldg_frame = ttk.LabelFrame(settings_frame, text="Building Settings (Band 2)", padding="10")
        bldg_frame.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.W, tk.E), padx=5)
        bldg_frame.columnconfigure(1, weight=1) # Make sliders/entries expand a bit
        self._create_settings_widgets(bldg_frame,
                                      self.conf_thresh_bldg_var, self.conf_thresh_bldg_display_var, # Updated vars
                                      self.simplify_bldg_var,
                                      self.min_area_bldg_var) # Removed max_hole_var

        # Roads Frame
        road_frame = ttk.LabelFrame(settings_frame, text="Road Settings (Band 1)", padding="10")
        road_frame.grid(row=0, column=1, sticky=(tk.N, tk.S, tk.W, tk.E), padx=5)
        road_frame.columnconfigure(1, weight=1)
        self._create_settings_widgets(road_frame,
                                      self.conf_thresh_road_var, self.conf_thresh_road_display_var, # Updated vars
                                      self.simplify_road_var,
                                      self.min_area_road_var,
                                      chaikin_var=self.smooth_roads_chaikin_var) # Pass Chaikin specific var

        # --- Controls Frame ---
        control_frame = ttk.Frame(main_frame, padding="5")
        control_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E))
        control_frame.columnconfigure(0, weight=1) # Center button

        self.run_button = ttk.Button(control_frame, text="Run Vectorization", command=self.start_processing)
        self.run_button.grid(row=0, column=0, pady=10) # Center horizontally

        # --- Log Frame ---
        log_frame = ttk.LabelFrame(main_frame, text="Log", padding="10")
        log_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=15, state='disabled', font=("TkFixedFont", 10)) # Monospaced font
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Start checking the queue for log messages
        self.master.after(100, self.process_log_queue)

    def _create_settings_widgets(self, parent_frame, conf_thresh_var, conf_thresh_display_var, simplify_var, min_area_var, max_hole_var=None, chaikin_var=None):
        """Helper to create the settings widgets within a frame."""
        # Updated label
        ttk.Label(parent_frame, text="Confidence Thr. (%):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)
        conf_thresh_scale = ttk.Scale(parent_frame, from_=0, to=100, orient=tk.HORIZONTAL, variable=conf_thresh_var, command=lambda v, tv=conf_thresh_display_var: tv.set(f"{float(v):.1f}%"))
        conf_thresh_scale.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=3)
        conf_thresh_label = ttk.Label(parent_frame, textvariable=conf_thresh_display_var, width=7)
        conf_thresh_label.grid(row=0, column=2, sticky=tk.W, padx=5, pady=3)

        ttk.Label(parent_frame, text="Simplify Tol.:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=3)
        simplify_entry = ttk.Entry(parent_frame, textvariable=simplify_var, width=10)
        simplify_entry.grid(row=1, column=1, columnspan=2, sticky=tk.W, padx=5, pady=3)

        ttk.Label(parent_frame, text="Min Area (map units²):").grid(row=2, column=0, sticky=tk.W, padx=5, pady=3)
        min_area_entry = ttk.Entry(parent_frame, textvariable=min_area_var, width=10)
        min_area_entry.grid(row=2, column=1, columnspan=2, sticky=tk.W, padx=5, pady=3)

        # REMOVED: Max Hole Entry

        # Use row 3 for Chaikin if Max Hole isn't present
        widget_row = 3
        if max_hole_var is not None: # This condition is now always False
             widget_row = 3 # Kept for structure, but won't run
             ttk.Label(parent_frame, text="Max Hole (map units²):").grid(row=widget_row, column=0, sticky=tk.W, padx=5, pady=3)
             max_hole_entry = ttk.Entry(parent_frame, textvariable=max_hole_var, width=10)
             max_hole_entry.grid(row=widget_row, column=1, columnspan=2, sticky=tk.W, padx=5, pady=3)
             widget_row += 1 # Increment row for next widget


        if chaikin_var is not None: # Road specific
            ttk.Label(parent_frame, text="Chaikin Iter.:").grid(row=widget_row, column=0, sticky=tk.W, padx=5, pady=3) # Use correct row
            # Use Spinbox for integer input
            chaikin_spinbox = ttk.Spinbox(parent_frame, from_=0, to=20, increment=1, textvariable=chaikin_var, width=8, wrap=False)
            chaikin_spinbox.grid(row=widget_row, column=1, columnspan=2, sticky=tk.W, padx=5, pady=3)


    def browse_input(self):
        """Opens file dialog to select input raster."""
        # Added common raster filetypes
        filepath = filedialog.askopenfilename(
            title="Select Input Raster",
            filetypes=[("GeoTIFF", "*.tif *.tiff"),
                       ("Erdas Imagine", "*.img"),
                       ("ENVI", "*.dat *.hdr"),
                       ("All files", "*.*")]
            )
        if filepath:
            self.input_raster_var.set(filepath)
            if not self.output_dir_var.get():
                 self.output_dir_var.set(os.path.dirname(filepath))


    def browse_output_dir(self):
        """Opens directory dialog to select output folder."""
        dirpath = filedialog.askdirectory(title="Select Output Directory")
        if dirpath:
            self.output_dir_var.set(dirpath)

    def log(self, message):
        """Appends a message to the log text area in a thread-safe way."""
        # This function itself runs in the main thread, triggered by process_log_queue
        self.log_text.configure(state='normal')
        self.log_text.insert(tk.END, str(message) + '\n')
        self.log_text.configure(state='disabled')
        self.log_text.see(tk.END) # Auto-scroll

    def process_log_queue(self):
        """Checks the queue for messages from the worker thread and logs them."""
        try:
            while True: # Process all messages currently in the queue
                msg = self.log_queue.get_nowait()
                if msg == "PROCESS_COMPLETE_SUCCESS":
                    self.run_button.config(state=tk.NORMAL) # Re-enable button first
                    self.log(">>> Process completed successfully!")
                    messagebox.showinfo("Success", "Vectorization process completed successfully!")
                elif msg == "PROCESS_COMPLETE_FAILURE":
                    self.run_button.config(state=tk.NORMAL) # Re-enable button first
                    self.log(">>> Process failed or completed with errors.")
                    messagebox.showerror("Failure", "Vectorization process failed or completed with errors. Check log.")
                else:
                    self.log(msg) # Log normal messages
        except queue.Empty:
            pass # No messages currently
        finally:
            # Reschedule itself
            self.master.after(100, self.process_log_queue)


    def validate_inputs(self):
        """Performs basic validation on GUI inputs."""
        # ... (validation for input/output paths remains same) ...
        if not self.input_raster_var.get() or not os.path.isfile(self.input_raster_var.get()):
            messagebox.showerror("Input Error", "Please select a valid input raster file.")
            return False
        if not self.output_dir_var.get():
             # Try creating dir if it doesn't exist? Or just require existing?
             # For now, require it exists or is selectable.
             messagebox.showerror("Input Error", "Please select an output directory.")
             return False
        elif not os.path.isdir(self.output_dir_var.get()):
             if messagebox.askyesno("Create Directory?", f"Output directory '{self.output_dir_var.get()}' does not exist.\nCreate it?"):
                 try:
                      os.makedirs(self.output_dir_var.get(), exist_ok=True)
                 except Exception as e:
                      messagebox.showerror("Directory Error", f"Could not create output directory:\n{e}")
                      return False
             else:
                 return False

        if not self.output_name_var.get().strip():
             messagebox.showerror("Input Error", "Output filename cannot be empty.")
             return False
        if not self.output_name_var.get().lower().endswith(".gpkg"):
             if messagebox.askyesno("Filename Warning", "Output filename does not end with '.gpkg'.\nThis might cause issues with GeoPackage drivers.\nContinue anyway?"):
                 pass
             else:
                 return False


        # Validate numeric inputs
        try:
            # Make sure to get from the correct vars
            float(self.simplify_bldg_var.get())
            float(self.min_area_bldg_var.get())
            # REMOVED: max_hole_bldg_var check
            float(self.simplify_road_var.get())
            float(self.min_area_road_var.get())
            int(self.smooth_roads_chaikin_var.get())

            # Check non-negativity
            if any(v.get() < 0 for v in [self.simplify_bldg_var, self.min_area_bldg_var,
                                         self.simplify_road_var, self.min_area_road_var, self.smooth_roads_chaikin_var]):
                 raise ValueError("Numeric parameters cannot be negative.")

            # Check confidence thresholds are within 0-100
            if not (0 <= self.conf_thresh_bldg_var.get() <= 100):
                 raise ValueError("Building confidence threshold must be between 0 and 100.")
            if not (0 <= self.conf_thresh_road_var.get() <= 100):
                 raise ValueError("Road confidence threshold must be between 0 and 100.")


        except ValueError as e:
            messagebox.showerror("Input Error", f"Invalid numeric input: {e}\nPlease enter valid numbers in the correct ranges.")
            return False

        return True

    def start_processing(self):
        """Gathers parameters, validates, and starts the processing thread."""
        if not self.validate_inputs():
            return

        # Clear log
        self.log_text.configure(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state='disabled')
        # Log start immediately
        self.log("Starting processing thread...")
        self.master.update_idletasks() # Ensure log message appears


        # Gather parameters (using updated var names)
        params = {
            'input_raster': self.input_raster_var.get(),
            'output_dir': self.output_dir_var.get(),
            'output_name': self.output_name_var.get(),
            'force': self.force_overwrite_var.get(),
            'conf_thresh_bldg_pct': self.conf_thresh_bldg_var.get(),
            'simplify_bldg': self.simplify_bldg_var.get(),
            'min_area_bldg': self.min_area_bldg_var.get(),
            # REMOVED: max_hole_bldg
            'conf_thresh_road_pct': self.conf_thresh_road_var.get(),
            'simplify_road': self.simplify_road_var.get(),
            'min_area_road': self.min_area_road_var.get(),
            'smooth_roads_chaikin': self.smooth_roads_chaikin_var.get(),
        }

        self.run_button.config(state=tk.DISABLED) # Disable button during run

        # Run run_processing in a separate thread
        self.processing_thread = threading.Thread(
            target=run_processing,
            args=(params, self.log_queue),
            daemon=True # Allows main program to exit even if thread is running
        )
        self.processing_thread.start()

# --- Main Execution ---
if __name__ == "__main__":
    # Enable Tile support on newer Tk versions (for better Mac rendering)
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except ImportError: # Not windows
        pass
    except AttributeError: # Older windows / Tk
        pass


    root = tk.Tk()
    app = VectorizationApp(root)
    root.mainloop()