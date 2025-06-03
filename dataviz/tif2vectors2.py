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
DEFAULT_OUTPUT_NAME = "vectorized_merged_output.gpkg" # Updated default name
DEFAULT_CONFIDENCE_THRESHOLD_BUILDING = 40.0
DEFAULT_CONFIDENCE_THRESHOLD_ROAD = 40.0
DEFAULT_MIN_AREA_BUILDING = 50.0
DEFAULT_SIMPLIFY_BUILDING = 1.0
DEFAULT_MIN_AREA_ROAD = 20.0
DEFAULT_SIMPLIFY_ROAD = 1.5
DEFAULT_CHAIKIN_ITERATIONS_ROAD = 0

# --- GDAL/OGR Setup ---
gdal.UseExceptions()
ogr.UseExceptions()

# --- Helper Functions for Processing ---
def log_message(logger_queue, message):
    """Helper to put messages onto the GUI queue."""
    if logger_queue:
        try:
            logger_queue.put(str(message))
        except Exception as e:
            try:
                logger_queue.put(f"[Logging Error: Could not convert message to string - {type(message)} - {e}]")
            except: pass
    else:
        print(message)

def get_raster_info(raster_ds, logger_queue=None):
    """Extracts key information from a GDAL Raster DataSource."""
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
    info['srs'] = srs

    if info['projection_wkt']:
        try:
            srs.ImportFromWkt(info['projection_wkt'])
        except Exception:
            log_message(logger_queue, "Warning: Could not import SRS from WKT projection string.")
            info['projection_wkt'] = None # Clear if import failed

    # Attempt to get projection ref if WKT was initially empty or failed
    if not info['projection_wkt'] and raster_ds.GetProjectionRef():
        proj_ref = raster_ds.GetProjectionRef()
        try:
            # Create a new SRS object for this attempt to avoid partial state
            srs_ref = osr.SpatialReference()
            srs_ref.ImportFromWkt(proj_ref) # GDAL GetProjectionRef often returns WKT
            info['srs'] = srs_ref # Replace srs object
            info['projection_wkt'] = proj_ref # Store the successful WKT
        except Exception:
            log_message(logger_queue, "Warning: Could not import SRS from GetProjectionRef() string.")

    if not info['projection_wkt'] or not info['geotransform'] or info['geotransform'] == (0, 1, 0, 0, 0, 1):
        log_message(logger_queue, "Warning: Raster may lack a valid projection or geotransform. Results might be incorrect.")
    
    # Ensure 'srs' object is valid even if projection_wkt is None
    if not info['projection_wkt'] and info['srs']:
        # If WKT is none but SRS object exists, try to re-populate WKT from SRS
        try:
            wkt_check = info['srs'].ExportToWkt()
            if wkt_check:
                 info['projection_wkt'] = wkt_check
            else: # SRS object is empty or invalid
                 info['srs'] = osr.SpatialReference() # Reset to empty valid SRS
                 log_message(logger_queue, "Warning: SRS object was present but yielded no WKT. Resetting SRS.")
        except:
            info['srs'] = osr.SpatialReference() # Reset on error
            log_message(logger_queue, "Warning: Error exporting WKT from existing SRS object. Resetting SRS.")


    return info

def clear_and_repopulate_layer(layer, features_data, layer_name, action_desc="updating", logger_queue=None):
    layer_defn = layer.GetLayerDefn()
    original_count = layer.GetFeatureCount()
    kept_count = len(features_data)

    if kept_count == 0 and original_count == 0:
        log_message(logger_queue, f"      Skipping rewrite for {action_desc}: layer '{layer_name}' is already empty.")
        return True

    log_message(logger_queue, f"      Repopulating layer '{layer_name}' for {action_desc}: Clearing {original_count} features, adding {kept_count} back...")

    deleted_count = 0
    try: 
        layer.StartTransaction()
        fids_to_delete = [feat.GetFID() for feat in layer] 
        layer.ResetReading() 
        for fid in fids_to_delete:
            err = layer.DeleteFeature(fid)
            if err == ogr.OGRERR_NONE:
                deleted_count += 1
        
        if deleted_count != original_count:
            log_message(logger_queue, f"        Warning: Deleted {deleted_count}/{original_count} features during clear operation.")

    except Exception as e:
        layer.RollbackTransaction() 
        log_message(logger_queue, f"        Error clearing features in '{layer_name}': {e}")
        return False

    added_count = 0
    try: 
        for data in features_data:
            geom = data.get('geom')
            attrs = data.get('attributes', {})

            if geom is None or geom.IsEmpty():
                continue

            new_feature = ogr.Feature(layer_defn)
            geom_clone = geom.Clone()
            if new_feature.SetGeometry(geom_clone) != ogr.OGRERR_NONE:
                log_message(logger_queue, f"        Warning: Failed to set geometry during repopulation for feature with attrs: {attrs}. Skipping.")
                if new_feature: new_feature.Destroy()
                continue 

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
        
        layer.CommitTransaction() 

        if added_count != kept_count:
            log_message(logger_queue, f"        Warning: Added {added_count}/{kept_count} features during repopulation.")

    except Exception as e:
        layer.RollbackTransaction() 
        log_message(logger_queue, f"        Error adding features back to '{layer_name}': {e}")
        log_message(logger_queue, traceback.format_exc()) 
        return False

    final_count = layer.GetFeatureCount()
    log_message(logger_queue, f"      Layer '{layer_name}' {action_desc} complete. Final feature count: {final_count} (Expected: {kept_count})")
    if final_count != kept_count:
        log_message(logger_queue, f"        Warning: Final count {final_count} does not match expected count {kept_count}!")
    
    return True

def simplify_layer(layer, tolerance, layer_name, logger_queue=None):
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
                geom_clone = geom.Clone()
                simplified = geom_clone.SimplifyPreserveTopology(tolerance)
                if simplified and not simplified.IsEmpty():
                    simplified_geom = simplified 
                else:
                    simplified_geom = geom.Clone() 
            except Exception as e:
                log_message(logger_queue, f"\n        Warning: SimplifyPreserveTopology failed for FID {feature.GetFID()}: {e}. Keeping original geometry.")
                simplified_geom = geom.Clone() 
        
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
            removed_count +=1 

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

def _apply_chaikin_to_ring(points, iterations, logger_queue=None):
    if not points or len(points) < 4:
        return points
    current_points = list(points)
    for iter_num in range(iterations):
        new_points = []
        num_pts = len(current_points)
        if num_pts < 4: 
            log_message(logger_queue, f"        Warning: Chaikin smoothing reduced points below minimum (4) at iteration {iter_num}. Stopping early.")
            break

        p0_prev = current_points[num_pts - 2] # Second to last point for closing segment
        p1_first = current_points[0]      # First point for closing segment

        # Calculate Q0 and Q1 for the segment connecting the last actual point to the first (closing the loop)
        # This means we need to conceptually use current_points[-1] (which is same as current_points[0] if closed)
        # and current_points[0]. But GetPoints() gives list where last != first.
        # Chaikin operates on open polylines usually, then closes them.
        # If current_points is [P0, P1, P2, P0] (closed from OGR), we operate on [P0,P1,P2] then ensure closure.
        # For a ring like (A, B, C, A), GetPoints() might give [(Ax,Ay), (Bx,By), (Cx,Cy), (Ax,Ay)]
        # Or sometimes it's [(Ax,Ay), (Bx,By), (Cx,Cy)] if it's an OGR ring not yet forced to close by adding start point.
        # Let's assume points from GetPoints() already has the last point == first point for a closed ring.
        
        # Chaikin's rule uses P_i and P_{i+1}
        # The first new segment is from R0 (derived from P0, P1) and Q1 (derived from P0, P1)
        # The last new segment is from R_N-1 (derived from P_N-1, P0) and Q0 (derived from P_N-1, P0)
        
        # Iterating from i=0 to num_pts-2 (if last point is duplicate of first)
        # or i=0 to num_pts-1 (if last point is unique before closure)
        
        # If points are [A, B, C, A] (num_pts = 4)
        # i=0: p0=A, p1=B -> qA, rA
        # i=1: p0=B, p1=C -> qB, rB
        # i=2: p0=C, p1=A -> qC, rC
        # Result: [qA, rA, qB, rB, qC, rC, qA (to close)]
        
        # The provided _apply_chaikin_to_ring seems to have a specific logic for handling closure
        # that might be slightly different from textbook, let's stick to its original intent.
        # Original logic:
        # p0 = current_points[num_pts - 2]
        # p1 = current_points[0]
        # This segment seems to be handled separately and prepended/appended.
        
        temp_ring_pts = []
        for i in range(num_pts -1): # Iterate through segments P_i to P_{i+1}
            p_i = current_points[i]
            p_i_plus_1 = current_points[i+1]

            r_x = 0.75 * p_i[0] + 0.25 * p_i_plus_1[0]
            r_y = 0.75 * p_i[1] + 0.25 * p_i_plus_1[1]
            q_x = 0.25 * p_i[0] + 0.75 * p_i_plus_1[0]
            q_y = 0.25 * p_i[1] + 0.75 * p_i_plus_1[1]
            temp_ring_pts.append((r_x, r_y))
            temp_ring_pts.append((q_x, q_y))

        if temp_ring_pts:
            temp_ring_pts.append(temp_ring_pts[0]) # Close the new ring
            current_points = temp_ring_pts
        else: # Not enough points to form segments
            break 

    return current_points


def smooth_layer_chaikin(layer, iterations, layer_name, logger_queue=None):
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
            flat_geom_type = ogr.GT_Flatten(geom_type) 

            if flat_geom_type == ogr.wkbPolygon or flat_geom_type == ogr.wkbMultiPolygon:
                new_multi_poly = ogr.Geometry(ogr.wkbMultiPolygon)
                srs = geom.GetSpatialReference()
                if srs:
                    new_multi_poly.AssignSpatialReference(srs.Clone()) # Clone SRS

                num_parts = geom.GetGeometryCount() if flat_geom_type == ogr.wkbMultiPolygon else 1

                for k in range(num_parts):
                    part = geom.GetGeometryRef(k) if flat_geom_type == ogr.wkbMultiPolygon else geom
                    
                    if not part or part.IsEmpty() or ogr.GT_Flatten(part.GetGeometryType()) != ogr.wkbPolygon:
                        continue

                    new_poly = ogr.Geometry(ogr.wkbPolygon)
                    if srs: new_poly.AssignSpatialReference(srs.Clone())
                    num_rings = part.GetGeometryCount()

                    for i in range(num_rings):
                        ring = part.GetGeometryRef(i)
                        if not ring or ring.IsEmpty() or ogr.GT_Flatten(ring.GetGeometryType()) != ogr.wkbLinearRing:
                            continue
                        
                        points = ring.GetPoints() 
                        if not points or len(points) < 4: 
                            new_poly.AddGeometry(ring.Clone()) 
                            continue

                        try:
                            points_2d = [(p[0], p[1]) for p in points]
                            # Ensure the ring is explicitly closed for Chaikin if GetPoints doesn't guarantee it
                            if points_2d[0] != points_2d[-1] and len(points_2d) > 1: # Check if not already closed
                                points_2d.append(points_2d[0])

                            smoothed_points_2d = _apply_chaikin_to_ring(points_2d, iterations, logger_queue)

                            if smoothed_points_2d and len(smoothed_points_2d) >= 4:
                                new_ring = ogr.Geometry(ogr.wkbLinearRing)
                                if srs: new_ring.AssignSpatialReference(srs.Clone())
                                has_z = len(points[0]) > 2
                                z_val = points[0][2] if has_z else 0.0 

                                for pt_idx, pt in enumerate(smoothed_points_2d):
                                    # Ensure last point closes the ring properly
                                    if pt_idx == len(smoothed_points_2d) -1 and smoothed_points_2d[0] != pt : # If Chaikin didn't close it
                                        if has_z:
                                            new_ring.AddPoint(smoothed_points_2d[0][0], smoothed_points_2d[0][1], z_val)
                                        else:
                                            new_ring.AddPoint(smoothed_points_2d[0][0], smoothed_points_2d[0][1])
                                        break # Ring is now closed by adding the first point

                                    if has_z:
                                        new_ring.AddPoint(pt[0], pt[1], z_val)
                                    else:
                                        new_ring.AddPoint(pt[0], pt[1])
                                
                                # Ensure the last point is same as first for a valid LinearRing by OGR
                                if new_ring.GetPointCount() > 0:
                                    p_first = new_ring.GetPoint_2D(0)
                                    p_last = new_ring.GetPoint_2D(new_ring.GetPointCount()-1)
                                    if p_first[0] != p_last[0] or p_first[1] != p_last[1]:
                                        if has_z: new_ring.AddPoint(p_first[0], p_first[1], z_val)
                                        else: new_ring.AddPoint(p_first[0], p_first[1])


                                if new_ring.IsValid():
                                    new_poly.AddGeometry(new_ring)
                                else:
                                    log_message(logger_queue, f"        Warning: Chaikin resulted in invalid ring geom for FID {feature.GetFID()}, part {k}, ring {i}. Using original ring.")
                                    new_poly.AddGeometry(ring.Clone())
                            else: 
                                new_poly.AddGeometry(ring.Clone())
                        except Exception as e:
                            log_message(logger_queue, f"\n        Error during Chaikin smoothing for FID {feature.GetFID()}, part {k}, ring {i}: {e}. Using original ring.")
                            log_message(logger_queue, traceback.format_exc())
                            new_poly.AddGeometry(ring.Clone())
                    
                    if not new_poly.IsEmpty():
                        if new_poly.IsValid():
                            err = new_multi_poly.AddGeometry(new_poly.Clone()) # Clone polygon before adding
                            if err != ogr.OGRERR_NONE:
                                log_message(logger_queue, f"        Warning: Failed to add smoothed polygon part {k} for FID {feature.GetFID()} to MultiPolygon. Error: {err}")
                        else:
                            log_message(logger_queue, f"        Warning: Polygon part {k} invalid after smoothing rings for FID {feature.GetFID()}. Skipping this part.")
                
                if not new_multi_poly.IsEmpty():
                    if not new_multi_poly.IsValid():
                        log_message(logger_queue, f"        Warning: Final MultiPolygon for FID {feature.GetFID()} is invalid after smoothing. Attempting MakeValid.")
                        repaired_multi = new_multi_poly.MakeValid()
                        if repaired_multi and not repaired_multi.IsEmpty() and repaired_multi.IsValid():
                            processed_geom = repaired_multi.Clone()
                        else:
                            log_message(logger_queue, f"          MakeValid failed for smoothed MultiPolygon FID {feature.GetFID()}. Keeping original.")
                            processed_geom = geom.Clone() 
                    else:
                        processed_geom = new_multi_poly.Clone()
                else: 
                    processed_geom = geom.Clone() 
            else: 
                processed_geom = geom.Clone()
        else: 
            processed_geom = None

        processed_data.append({'geom': processed_geom, 'attributes': attrs})
        
        processed_count += 1
        if processed_count % 1000 == 0: 
            elapsed = time.time() - start_time
            log_message(logger_queue, f"        Smoothed {processed_count}/{feature_count} features in {elapsed:.1f}s...")

        if feature: feature.Destroy()
        feature = layer.GetNextFeature()

    success = clear_and_repopulate_layer(layer, processed_data, layer_name, action_desc, logger_queue)
    log_message(logger_queue, f"    Finished {action_desc} for '{layer_name}' in {time.time() - start_time:.2f}s.")
    return success

def fix_layer_geometries(layer, layer_name, logger_queue=None):
    action_desc = "geometry fixing"
    start_time = time.time()
    log_message(logger_queue, f"    Applying {action_desc} to layer '{layer_name}'...")
    feature_count = layer.GetFeatureCount()
    if feature_count == 0:
        log_message(logger_queue, f"    Layer '{layer_name}' is empty, skipping {action_desc}.")
        return True

    layer_defn = layer.GetLayerDefn()
    field_names = [layer_defn.GetFieldDefn(i).GetNameRef() for i in range(layer_defn.GetFieldCount())]
    target_geom_type = layer.GetGeomType() 
    target_flat_geom_type = ogr.GT_Flatten(target_geom_type) 

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
        final_geom = None 

        if geom and not geom.IsEmpty():
            if geom.IsValid():
                final_geom = geom.Clone() 
            else:
                invalid_count += 1
                try:
                    repaired_geom = geom.MakeValid()
                except Exception as make_valid_err:
                    log_message(logger_queue, f"        Warning: MakeValid() crashed for FID {fid}: {make_valid_err}. Discarding feature.")
                    repaired_geom = None
                    discarded_count +=1
                
                if repaired_geom and not repaired_geom.IsEmpty():
                    repaired_type = repaired_geom.GetGeometryType()
                    repaired_flat_type = ogr.GT_Flatten(repaired_type)

                    if repaired_flat_type == target_flat_geom_type:
                        if repaired_geom.IsValid(): 
                            final_geom = repaired_geom.Clone()
                            repaired_count += 1
                        else:
                            log_message(logger_queue, f"        Warning: MakeValid() produced an invalid geometry of type {ogr.GeometryTypeToName(repaired_type)} for FID {fid}. Discarding feature.")
                            discarded_count += 1
                    elif repaired_flat_type == ogr.wkbGeometryCollection and \
                         (target_flat_geom_type == ogr.wkbPolygon or target_flat_geom_type == ogr.wkbMultiPolygon):
                        collection_extract = ogr.Geometry(target_geom_type) 
                        srs = geom.GetSpatialReference()
                        if srs: collection_extract.AssignSpatialReference(srs.Clone())
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
                            if collection_extract.IsValid():
                                final_geom = collection_extract.Clone() # Keep the extracted polygons (Clone before assigning)
                                repaired_count += 1
                                log_message(logger_queue, f"        Info: Repaired FID {fid} from GeometryCollection, extracted valid {ogr.GeometryTypeToName(target_geom_type)}.")
                            else:
                                log_message(logger_queue, f"        Warning: Extracted geometry from GeometryCollection for FID {fid} is invalid. Discarding feature.")
                                discarded_count += 1
                        else:
                            log_message(logger_queue, f"        Warning: MakeValid() produced GeometryCollection for FID {fid}, but no valid {ogr.GeometryTypeToName(target_geom_type)} parts found. Discarding feature.")
                            discarded_count += 1
                    else:
                        log_message(logger_queue, f"        Warning: MakeValid() repaired FID {fid} to an incompatible type ({ogr.GeometryTypeToName(repaired_type)} for target {ogr.GeometryTypeToName(target_geom_type)}). Discarding feature.")
                        discarded_count += 1
                else:
                    log_message(logger_queue, f"        Warning: MakeValid() failed or produced empty geometry for FID {fid}. Discarding feature.")
                    discarded_count += 1
        else:
            discarded_count += 1
        
        if final_geom:
            # Ensure the final_geom also has SRS if the original did
            if geom and geom.GetSpatialReference() and final_geom.GetSpatialReference() is None:
                 final_geom.AssignSpatialReference(geom.GetSpatialReference().Clone())
            processed_data.append({'geom': final_geom, 'attributes': attrs}) # final_geom is already a clone or a new geom

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
                if geom and not geom.IsEmpty() and geom.IsValid(): # Ensure geom is valid before keeping
                    attrs = {name: feature.GetField(name) for name in field_names}
                    features_to_keep.append({'geom': geom.Clone() if geom else None, 'attributes': attrs})
                    kept_count += 1
        except Exception as e:
            log_message(logger_queue, f"\n        Warning: Error reading DN field for FID {feature.GetFID()}: {e}. Skipping feature.")

        processed_count += 1
        if processed_count % 5000 == 0:
            elapsed = time.time() - start_time
            log_message(logger_queue, f"        DN filter checked {processed_count}/{feature_count} features in {elapsed:.1f}s...")

        if feature: feature.Destroy()
        feature = layer.GetNextFeature()

    if kept_count == feature_count and feature_count > 0: # If no features were removed
        log_message(logger_queue, f"      Skipping rewrite for {action_desc}: all {feature_count} features met criteria.")
        return True

    success = clear_and_repopulate_layer(layer, features_to_keep, layer_name, action_desc, logger_queue)
    log_message(logger_queue, f"    Finished {action_desc} for '{layer_name}' in {time.time() - start_time:.2f}s.")
    return success

def initial_polygonize_band(raster_ds, band_num, threshold_255, out_layer, layer_name, logger_queue=None, progress_callback=None):
    """Polygonizes a raster band based on a threshold and appends to out_layer."""
    log_message(logger_queue, f"--- Initial Polygonization: Band {band_num} ({layer_name}) ---") # layer_name now includes source raster
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
        return False

    threshold_value = int(threshold_255)
    log_message(logger_queue, f"  Applying confidence threshold >= {threshold_value} ({threshold_value/255.0*100:.1f}%)...")
    thresholded_array = (band_array >= threshold_value).astype(np.uint8)
    band_array = None 
    pixels_above = np.sum(thresholded_array)

    if pixels_above == 0:
        log_message(logger_queue, f"  Warning: No pixels meet the confidence threshold >= {threshold_value} in current raster. No features added to '{layer_name}'.")
        return True # Successful in the sense that no data met criteria
    else:
        log_message(logger_queue, f"  Found {pixels_above} pixels >= confidence threshold in current raster.")

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
        thresholded_array = None 
        temp_band.FlushCache()
        temp_band.SetNoDataValue(0) # Pixels with 0 will not be polygonized

    except Exception as e:
        log_message(logger_queue, f"Error setting up temporary in-memory raster: {e}")
        if temp_ds: temp_ds = None 
        temp_band = None
        return False

    log_message(logger_queue, "  Polygonizing (using 8-connectedness) into target layer...")
    dn_field_index = out_layer.GetLayerDefn().GetFieldIndex('DN')
    if dn_field_index < 0:
        log_message(logger_queue, "Error: 'DN' field not found in the output layer before polygonization.")
        if temp_ds: temp_ds = None; temp_band = None
        return False

    poly_opts = ['8CONNECTED=YES'] 
    # gdal.Polygonize appends to the layer by default if it's not a new layer.
    # Mask band (second arg) is None to use the temp_band itself as mask implicitly with NoDataValue
    count_before = out_layer.GetFeatureCount()
    result = gdal.Polygonize(temp_band, None, out_layer, dn_field_index, poly_opts, callback=progress_callback)
    count_after = out_layer.GetFeatureCount()

    if temp_ds: temp_ds = None 
    temp_band = None

    if result != 0:
        err_msg = gdal.GetLastErrorMsg()
        if not err_msg or "unknown" in err_msg.lower():
            err_msg = f"Polygonize failed with error code {result}."
        log_message(logger_queue, f"Error during gdal.Polygonize: {err_msg}")
        return False
    else:
        log_message(logger_queue, f"  Polygonization added {count_after - count_before} features to '{layer_name}'.")

    log_message(logger_queue, f"--- Initial Polygonization for current raster's '{layer_name}' part finished in {time.time() - start_time:.2f}s ---")
    return True

# --- Core Processing Function (Called by GUI Thread) ---
def run_processing(params, logger_queue):
    log_message(logger_queue, "--- Starting Raster Vectorization ---")

    input_raster_paths = params['input_rasters'] # MODIFIED: Expects a list
    output_dir = params['output_dir']
    output_name = params['output_name']
    force_overwrite = params['force']
    confidence_threshold_bldg_pct = params['conf_thresh_bldg_pct']
    simplify_tolerance_buildings = params['simplify_bldg']
    min_area_buildings = params['min_area_bldg']
    confidence_threshold_road_pct = params['conf_thresh_road_pct']
    simplify_tolerance_roads = params['simplify_road']
    min_area_roads = params['min_area_road']
    chaikin_iterations_roads = params['smooth_roads_chaikin']

    threshold_255_buildings = max(0, min(255, int(confidence_threshold_bldg_pct / 100.0 * 255)))
    threshold_255_roads = max(0, min(255, int(confidence_threshold_road_pct / 100.0 * 255)))

    log_message(logger_queue, "\nParameters:")
    # MODIFIED: Log multiple input rasters
    if input_raster_paths:
        log_message(logger_queue, f"  Input Rasters ({len(input_raster_paths)} files):")
        for p_idx, p_path_log in enumerate(input_raster_paths):
            log_message(logger_queue, f"    [{p_idx+1}] {os.path.basename(p_path_log)}")
    else:
        log_message(logger_queue, "  Input Rasters: None selected (Error state)")

    log_message(logger_queue, f"  Output Directory: {output_dir}")
    log_message(logger_queue, f"  Output Filename: {output_name}")
    log_message(logger_queue, f"  Overwrite Existing: {'Yes' if force_overwrite else 'No'}")
    log_message(logger_queue, f"  Building Settings:")
    log_message(logger_queue, f"    Confidence Threshold: {confidence_threshold_bldg_pct:.1f}% ({threshold_255_buildings}/255)")
    log_message(logger_queue, f"    Simplify Tolerance: {simplify_tolerance_buildings} map units")
    log_message(logger_queue, f"    Min Area: {min_area_buildings} sq map units")
    log_message(logger_queue, f"  Road Settings:")
    log_message(logger_queue, f"    Confidence Threshold: {confidence_threshold_road_pct:.1f}% ({threshold_255_roads}/255)")
    log_message(logger_queue, f"    Simplify Tolerance: {simplify_tolerance_roads} map units")
    log_message(logger_queue, f"    Min Area: {min_area_roads} sq map units")
    smoothing_status = f"Enabled ({chaikin_iterations_roads} iterations)" if chaikin_iterations_roads > 0 else "Disabled"
    log_message(logger_queue, f"    Chaikin Smoothing: {smoothing_status}")
    log_message(logger_queue, "-" * 20)

    if not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir, exist_ok=True)
            log_message(logger_queue, f"Created output directory: {output_dir}")
        except OSError as e:
            log_message(logger_queue, f"Error: Could not create output directory '{output_dir}': {e}")
            logger_queue.put("PROCESS_COMPLETE_FAILURE")
            return False

    output_gpkg_path = os.path.join(output_dir, output_name)

    if os.path.exists(output_gpkg_path):
        if force_overwrite:
            log_message(logger_queue, f"Output file '{output_gpkg_path}' exists. Overwriting...")
            try:
                driver = ogr.GetDriverByName("GPKG")
                if driver:
                    test_ds = None # Ensure GPKG is not locked
                    try: test_ds = driver.Open(output_gpkg_path, 0)
                    except: pass
                    finally:
                        if test_ds: test_ds = None
                    
                    delete_success = driver.DeleteDataSource(output_gpkg_path)
                    if delete_success != ogr.OGRERR_NONE:
                        if os.path.exists(output_gpkg_path):
                            log_message(logger_queue, f"  GDAL driver DeleteDataSource indicated non-success ({delete_success}). Attempting os.remove...")
                            os.remove(output_gpkg_path)
                            log_message(logger_queue, f"  Successfully deleted existing file using os.remove.")
                else: # Fallback if driver issue
                    os.remove(output_gpkg_path)
            except Exception as e:
                log_message(logger_queue, f"Error: Could not remove existing output file '{output_gpkg_path}': {e}")
                logger_queue.put("PROCESS_COMPLETE_FAILURE")
                return False
        else:
            log_message(logger_queue, f"\nError: Output file exists: '{output_gpkg_path}'. Enable 'Force Overwrite' checkbox.")
            logger_queue.put("PROCESS_COMPLETE_FAILURE")
            return False

    # --- NEW: Validate Input Rasters (Projection Check) ---
    log_message(logger_queue, "\n--- Validating Input Rasters ---")
    if not input_raster_paths:
        log_message(logger_queue, "Error: No input rasters provided.")
        logger_queue.put("PROCESS_COMPLETE_FAILURE")
        return False

    first_raster_ds_val = None # For validation only
    target_srs = None
    first_raster_path_val = input_raster_paths[0]

    try:
        log_message(logger_queue, f"Opening first raster for validation: {os.path.basename(first_raster_path_val)}")
        first_raster_ds_val = gdal.Open(first_raster_path_val, gdal.GA_ReadOnly)
        if first_raster_ds_val is None:
            raise RuntimeError(f"Could not open first raster file: {os.path.basename(first_raster_path_val)}")
        
        first_raster_info_val = get_raster_info(first_raster_ds_val, logger_queue)
        if not first_raster_info_val or not first_raster_info_val['srs'] or not first_raster_info_val['projection_wkt']: # Check WKT for valid SRS
            raise RuntimeError(f"Could not get a valid SRS from first raster: {os.path.basename(first_raster_path_val)}")
        
        target_srs = first_raster_info_val['srs'].Clone()
        
        if first_raster_info_val['bands'] < 2:
            raise RuntimeError(f"Input raster {os.path.basename(first_raster_path_val)} needs at least 2 bands (Roads=1, Buildings=2). Found: {first_raster_info_val['bands']}")
        log_message(logger_queue, f"  First raster SRS (Name: {target_srs.GetName() or 'N/A'}, Auth: {target_srs.GetAuthorityName(None)}-{target_srs.GetAuthorityCode(None) or 'N/A'}) seems valid.")


        for i in range(1, len(input_raster_paths)):
            current_raster_path_val = input_raster_paths[i]
            log_message(logger_queue, f"  Validating: {os.path.basename(current_raster_path_val)}")
            current_ds_val = None
            try:
                current_ds_val = gdal.Open(current_raster_path_val, gdal.GA_ReadOnly)
                if current_ds_val is None:
                    raise RuntimeError(f"Could not open raster file: {os.path.basename(current_raster_path_val)}")
                
                current_info_val = get_raster_info(current_ds_val, logger_queue)
                if not current_info_val or not current_info_val['srs'] or not current_info_val['projection_wkt']: # Check WKT
                    raise RuntimeError(f"Could not get a valid SRS from {os.path.basename(current_raster_path_val)}")
                
                if current_info_val['bands'] < 2:
                    raise RuntimeError(f"Input raster {os.path.basename(current_raster_path_val)} needs at least 2 bands. Found: {current_info_val['bands']}")

                if not target_srs.IsSame(current_info_val['srs']):
                    srs1_name = target_srs.GetName() or target_srs.ExportToProj4() or "Unknown SRS 1"
                    srs2_name = current_info_val['srs'].GetName() or current_info_val['srs'].ExportToProj4() or "Unknown SRS 2"
                    log_message(logger_queue, f"Error: Projection mismatch detected!")
                    log_message(logger_queue, f"  First raster ({os.path.basename(first_raster_path_val)}): {srs1_name}")
                    log_message(logger_queue, f"  Current raster ({os.path.basename(current_raster_path_val)}): {srs2_name}")
                    raise RuntimeError("Input rasters must have the same projection.")
            finally:
                if current_ds_val: current_ds_val = None
        log_message(logger_queue, "All rasters appear to have matching and valid projections.")

    except Exception as e:
        log_message(logger_queue, f"Error during input raster validation: {e}")
        log_message(logger_queue, traceback.format_exc())
        if first_raster_ds_val: first_raster_ds_val = None
        logger_queue.put("PROCESS_COMPLETE_FAILURE")
        return False
    finally:
        if first_raster_ds_val: first_raster_ds_val = None # Close the validation raster

    # Warning for geographic CRS (using validated target_srs)
    if not target_srs or not target_srs.IsProjected():
        log_message(logger_queue, "Warning: The common SRS of input rasters is missing, invalid, or geographic.")
        log_message(logger_queue, "  Area/Simplification units are based on map units; results may be incorrect for geographic CRS.")
        log_message(logger_queue, "  Consider reprojecting inputs to a projected CRS (e.g., UTM) first if values seem off.")


    # --- Create Output GeoPackage & Process ---
    log_message(logger_queue, f"\nCreating output GeoPackage: {output_gpkg_path}")
    gpkg_driver = ogr.GetDriverByName('GPKG')
    if not gpkg_driver:
        log_message(logger_queue, "Error: GPKG driver not available in this GDAL installation.")
        logger_queue.put("PROCESS_COMPLETE_FAILURE")
        return False

    out_ds = None
    roads_layer = None # Define before try block for finally clause
    buildings_layer = None
    success_roads = False
    success_buildings = False
    roads_layer_name = "roads_vector"
    buildings_layer_name = "buildings_vector"

    try:
        out_ds = gpkg_driver.CreateDataSource(output_gpkg_path)
        if out_ds is None:
            raise ogr.OGRError(f"Could not create GeoPackage datasource: {output_gpkg_path}")

        dn_field = ogr.FieldDefn('DN', ogr.OFTInteger)

        # Create layers ONCE
        log_message(logger_queue, f"Creating layer '{roads_layer_name}' in output.")
        roads_layer = out_ds.CreateLayer(roads_layer_name, srs=target_srs, geom_type=ogr.wkbMultiPolygon)
        if not roads_layer:
            raise ogr.OGRError(f"Failed to create layer: '{roads_layer_name}'")
        roads_layer.CreateField(dn_field)

        log_message(logger_queue, f"Creating layer '{buildings_layer_name}' in output.")
        buildings_layer = out_ds.CreateLayer(buildings_layer_name, srs=target_srs, geom_type=ogr.wkbMultiPolygon)
        if not buildings_layer:
            raise ogr.OGRError(f"Failed to create layer: '{buildings_layer_name}'")
        buildings_layer.CreateField(dn_field)

        # --- MODIFIED: Polygonization Loop (Iterate through each raster) ---
        all_poly_ok_roads = True
        all_poly_ok_buildings = True

        for raster_idx, current_input_raster_path in enumerate(input_raster_paths):
            log_message(logger_queue, f"\n===== PROCESSING RASTER {raster_idx + 1}/{len(input_raster_paths)}: {os.path.basename(current_input_raster_path)} =====")
            current_raster_ds_proc = None # For processing this specific raster
            try:
                current_raster_ds_proc = gdal.Open(current_input_raster_path, gdal.GA_ReadOnly)
                if current_raster_ds_proc is None:
                    log_message(logger_queue, f"Error: Could not open raster {os.path.basename(current_input_raster_path)} for polygonization. Skipping this raster.")
                    all_poly_ok_roads = False 
                    all_poly_ok_buildings = False
                    continue 

                # === Polygonize Roads (Band 1) for current raster ===
                if roads_layer:
                    poly_ok_roads_current = initial_polygonize_band(
                        current_raster_ds_proc, 1, threshold_255_roads, roads_layer, 
                        f"{roads_layer_name} (from {os.path.basename(current_input_raster_path)})", logger_queue
                    )
                    if not poly_ok_roads_current:
                        all_poly_ok_roads = False
                        log_message(logger_queue, f"Warning: Polygonization for roads failed for {os.path.basename(current_input_raster_path)}.")
                
                # === Polygonize Buildings (Band 2) for current raster ===
                if buildings_layer:
                    poly_ok_buildings_current = initial_polygonize_band(
                        current_raster_ds_proc, 2, threshold_255_buildings, buildings_layer, 
                        f"{buildings_layer_name} (from {os.path.basename(current_input_raster_path)})", logger_queue
                    )
                    if not poly_ok_buildings_current:
                        all_poly_ok_buildings = False
                        log_message(logger_queue, f"Warning: Polygonization for buildings failed for {os.path.basename(current_input_raster_path)}.")

            except Exception as e_loop:
                log_message(logger_queue, f"Critical error processing raster {os.path.basename(current_input_raster_path)}: {e_loop}")
                log_message(logger_queue, traceback.format_exc())
                all_poly_ok_roads = False # Mark as problematic if any raster fails critically
                all_poly_ok_buildings = False
            finally:
                if current_raster_ds_proc:
                    current_raster_ds_proc = None # Close dataset for current raster in loop
                    log_message(logger_queue, f"Closed raster: {os.path.basename(current_input_raster_path)}")
        
        # --- MODIFIED: Global Post-Processing (after all rasters are merged into layers) ---
        
        # === Post-Process Roads Layer (Global) ===
        if all_poly_ok_roads and roads_layer: # Check if layer exists
            if roads_layer.GetFeatureCount() > 0:
                log_message(logger_queue, f"\n===== GLOBAL POST-PROCESSING FOR MERGED '{roads_layer_name}' LAYER =====")
                simp_ok_r = simplify_layer(roads_layer, simplify_tolerance_roads, roads_layer_name, logger_queue)
                area_ok_r = filter_layer_by_min_area(roads_layer, min_area_roads, roads_layer_name, logger_queue) if simp_ok_r else False
                fix_geom_ok_r = fix_layer_geometries(roads_layer, roads_layer_name, logger_queue) if simp_ok_r and area_ok_r else False
                smooth_ok_r = True
                if chaikin_iterations_roads > 0:
                    if simp_ok_r and area_ok_r and fix_geom_ok_r:
                        smooth_ok_r = smooth_layer_chaikin(roads_layer, chaikin_iterations_roads, roads_layer_name, logger_queue)
                    else:
                        smooth_ok_r = False; log_message(logger_queue, "Skipping road Chaikin smoothing due to prior errors on merged layer.")
                dn_ok_final_r = filter_layer_by_dn(roads_layer, 1, roads_layer_name, logger_queue) if simp_ok_r and area_ok_r and fix_geom_ok_r and smooth_ok_r else False
                success_roads = simp_ok_r and area_ok_r and fix_geom_ok_r and smooth_ok_r and dn_ok_final_r
            else: # Layer is empty after merging
                log_message(logger_queue, f"Skipping global road post-processing: layer '{roads_layer_name}' is empty after merging all rasters.")
                success_roads = True # Considered successful if layer is correctly empty
        else: # Polygonization failed for one or more, or layer creation failed
            log_message(logger_queue, f"Skipping global road post-processing for '{roads_layer_name}' due to earlier polygonization/layer creation failures.")
            success_roads = False
        
        # === Post-Process Buildings Layer (Global) ===
        if all_poly_ok_buildings and buildings_layer: # Check if layer exists
            if buildings_layer.GetFeatureCount() > 0:
                log_message(logger_queue, f"\n===== GLOBAL POST-PROCESSING FOR MERGED '{buildings_layer_name}' LAYER =====")
                simp_ok_b = simplify_layer(buildings_layer, simplify_tolerance_buildings, buildings_layer_name, logger_queue)
                area_ok_b = filter_layer_by_min_area(buildings_layer, min_area_buildings, buildings_layer_name, logger_queue) if simp_ok_b else False
                fix_geom_ok_b = fix_layer_geometries(buildings_layer, buildings_layer_name, logger_queue) if simp_ok_b and area_ok_b else False
                dn_ok_b = filter_layer_by_dn(buildings_layer, 1, buildings_layer_name, logger_queue) if simp_ok_b and area_ok_b and fix_geom_ok_b else False
                success_buildings = simp_ok_b and area_ok_b and fix_geom_ok_b and dn_ok_b
            else: # Layer is empty after merging
                log_message(logger_queue, f"Skipping global building post-processing: layer '{buildings_layer_name}' is empty after merging all rasters.")
                success_buildings = True
        else: # Polygonization failed for one or more, or layer creation failed
            log_message(logger_queue, f"Skipping global building post-processing for '{buildings_layer_name}' due to earlier polygonization/layer creation failures.")
            success_buildings = False

    except Exception as e:
        log_message(logger_queue, f"\nAn critical error occurred during main processing: {e}")
        log_message(logger_queue, traceback.format_exc())
        success_roads = False # Ensure failure state
        success_buildings = False
    finally:
        log_message(logger_queue, "\nCleaning up resources...")
        # Layers are part of out_ds, setting out_ds to None will dereference them.
        # Explicitly setting them to None first is good practice if they were handled separately.
        if roads_layer is not None: roads_layer = None
        if buildings_layer is not None: buildings_layer = None
        if out_ds is not None:
            try:
                out_ds.FlushCache() # Important
                out_ds = None # This closes the datasource and releases layers
                log_message(logger_queue, "  Output GeoPackage closed.")
            except Exception as e_close:
                log_message(logger_queue, f"  Warning: Error closing output GeoPackage: {e_close}")
        # Individual raster_ds (current_raster_ds_proc and validation ones) are closed within their scopes.
        log_message(logger_queue, "Resource cleanup finished.")

    log_message(logger_queue, "\n===== PROCESSING SUMMARY =====")
    log_message(logger_queue, f"Roads processing overall successful: {success_roads}")
    log_message(logger_queue, f"Buildings processing overall successful: {success_buildings}")

    overall_success = success_roads and success_buildings

    if overall_success:
        log_message(logger_queue, f"\nProcessing complete. Output saved to: {output_gpkg_path}")
        try:
            final_ds_check = ogr.Open(output_gpkg_path, 0) # Read-only open for check
            if final_ds_check:
                final_roads_l = final_ds_check.GetLayerByName(roads_layer_name)
                final_bldg_l = final_ds_check.GetLayerByName(buildings_layer_name)
                log_message(logger_queue, f"Final feature counts:")
                log_message(logger_queue, f"  Layer '{roads_layer_name}': {final_roads_l.GetFeatureCount() if final_roads_l else 'Not Found/Error'}")
                log_message(logger_queue, f"  Layer '{buildings_layer_name}': {final_bldg_l.GetFeatureCount() if final_bldg_l else 'Not Found/Error'}")
                final_ds_check = None # Close it
            else:
                log_message(logger_queue, "Could not reopen final GeoPackage to verify feature counts.")
        except Exception as e_check:
            log_message(logger_queue, f"Error verifying final feature counts: {e_check}")
        logger_queue.put("PROCESS_COMPLETE_SUCCESS")
    else:
        log_message(logger_queue, "\nProcessing finished, but one or more stages failed or encountered errors.")
        log_message(logger_queue, f"Output file '{output_gpkg_path}' may be incomplete or contain errors.")
        logger_queue.put("PROCESS_COMPLETE_FAILURE")
    return overall_success

# --- Tkinter GUI Application ---
class VectorizationApp:
    def __init__(self, master):
        self.master = master
        master.title("Raster Vectorization Tool (Multi-File)")
        self.style = ttk.Style()
        available_themes = self.style.theme_names()
        if 'clam' in available_themes: self.style.theme_use('clam')
        elif 'alt' in available_themes: self.style.theme_use('alt')
        elif 'vista' in available_themes: self.style.theme_use('vista')
        elif 'aqua' in available_themes: self.style.theme_use('aqua')
        else: self.style.theme_use(available_themes[0])

        # --- Variables ---
        # MODIFIED: For multiple input files
        self.input_raster_paths = [] 
        self.input_display_var = tk.StringVar(value="No raster files selected.")

        self.output_dir_var = tk.StringVar()
        self.output_name_var = tk.StringVar(value=DEFAULT_OUTPUT_NAME)
        self.force_overwrite_var = tk.BooleanVar(value=False)

        self.conf_thresh_bldg_var = tk.DoubleVar(value=DEFAULT_CONFIDENCE_THRESHOLD_BUILDING)
        self.simplify_bldg_var = tk.DoubleVar(value=DEFAULT_SIMPLIFY_BUILDING)
        self.min_area_bldg_var = tk.DoubleVar(value=DEFAULT_MIN_AREA_BUILDING)

        self.conf_thresh_road_var = tk.DoubleVar(value=DEFAULT_CONFIDENCE_THRESHOLD_ROAD)
        self.simplify_road_var = tk.DoubleVar(value=DEFAULT_SIMPLIFY_ROAD)
        self.min_area_road_var = tk.DoubleVar(value=DEFAULT_MIN_AREA_ROAD)
        self.smooth_roads_chaikin_var = tk.IntVar(value=DEFAULT_CHAIKIN_ITERATIONS_ROAD)

        self.conf_thresh_bldg_display_var = tk.StringVar(value=f"{self.conf_thresh_bldg_var.get():.1f}%")
        self.conf_thresh_road_display_var = tk.StringVar(value=f"{self.conf_thresh_road_var.get():.1f}%")
        self.log_queue = queue.Queue()

        main_frame = ttk.Frame(master, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1) 
        main_frame.rowconfigure(3, weight=1) 

        io_frame = ttk.LabelFrame(main_frame, text="Input / Output", padding="10")
        io_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        io_frame.columnconfigure(1, weight=1)

        # MODIFIED: Input display
        ttk.Label(io_frame, text="Input Rasters:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.input_display_label = ttk.Label(io_frame, textvariable=self.input_display_var, anchor=tk.W, relief="sunken", padding=(2,2))
        self.input_display_label.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.browse_input_button = ttk.Button(io_frame, text="Browse...", command=self.browse_input_rasters) # MODIFIED: command name
        self.browse_input_button.grid(row=0, column=2, sticky=tk.E, padx=5, pady=2)

        ttk.Label(io_frame, text="Output Directory:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.output_dir_entry = ttk.Entry(io_frame, textvariable=self.output_dir_var, width=60)
        self.output_dir_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.browse_output_dir_button = ttk.Button(io_frame, text="Browse...", command=self.browse_output_dir)
        self.browse_output_dir_button.grid(row=1, column=2, sticky=tk.E, padx=5, pady=2)

        ttk.Label(io_frame, text="Output Filename:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.output_name_entry = ttk.Entry(io_frame, textvariable=self.output_name_var, width=30)
        self.output_name_entry.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)

        self.force_check = ttk.Checkbutton(io_frame, text="Force Overwrite", variable=self.force_overwrite_var)
        self.force_check.grid(row=3, column=1, sticky=tk.W, padx=5, pady=5)

        settings_frame = ttk.Frame(main_frame)
        settings_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        settings_frame.columnconfigure(0, weight=1)
        settings_frame.columnconfigure(1, weight=1)

        bldg_frame = ttk.LabelFrame(settings_frame, text="Building Settings (Band 2)", padding="10")
        bldg_frame.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.W, tk.E), padx=5)
        bldg_frame.columnconfigure(1, weight=1) 
        self._create_settings_widgets(bldg_frame,
                                      self.conf_thresh_bldg_var, self.conf_thresh_bldg_display_var,
                                      self.simplify_bldg_var,
                                      self.min_area_bldg_var)

        road_frame = ttk.LabelFrame(settings_frame, text="Road Settings (Band 1)", padding="10")
        road_frame.grid(row=0, column=1, sticky=(tk.N, tk.S, tk.W, tk.E), padx=5)
        road_frame.columnconfigure(1, weight=1)
        self._create_settings_widgets(road_frame,
                                      self.conf_thresh_road_var, self.conf_thresh_road_display_var,
                                      self.simplify_road_var,
                                      self.min_area_road_var,
                                      chaikin_var=self.smooth_roads_chaikin_var)

        control_frame = ttk.Frame(main_frame, padding="5")
        control_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E))
        control_frame.columnconfigure(0, weight=1) 

        self.run_button = ttk.Button(control_frame, text="Run Vectorization", command=self.start_processing)
        self.run_button.grid(row=0, column=0, pady=10) 

        log_frame = ttk.LabelFrame(main_frame, text="Log", padding="10")
        log_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=15, state='disabled', font=("TkFixedFont", 9))
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.master.after(100, self.process_log_queue)

    def _create_settings_widgets(self, parent_frame, conf_thresh_var, conf_thresh_display_var, simplify_var, min_area_var, chaikin_var=None):
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
        
        widget_row = 3 # Next available row
        if chaikin_var is not None:
            ttk.Label(parent_frame, text="Chaikin Iter.:").grid(row=widget_row, column=0, sticky=tk.W, padx=5, pady=3)
            chaikin_spinbox = ttk.Spinbox(parent_frame, from_=0, to=20, increment=1, textvariable=chaikin_var, width=8, wrap=False)
            chaikin_spinbox.grid(row=widget_row, column=1, columnspan=2, sticky=tk.W, padx=5, pady=3)

    # MODIFIED: browse_input to browse_input_rasters for multiple files
    def browse_input_rasters(self):
        filepaths = filedialog.askopenfilenames(
            title="Select Input Raster(s)",
            filetypes=[("GeoTIFF", "*.tif *.tiff"),
                       ("Erdas Imagine", "*.img"),
                       ("ENVI", "*.dat *.hdr"),
                       ("All files", "*.*")]
        )
        if filepaths:
            self.input_raster_paths = list(filepaths)
            if len(self.input_raster_paths) == 1:
                self.input_display_var.set(os.path.basename(self.input_raster_paths[0]))
            else:
                self.input_display_var.set(f"{len(self.input_raster_paths)} files selected")
            
            if self.input_raster_paths and not self.output_dir_var.get(): # Auto-set output dir
                self.output_dir_var.set(os.path.dirname(self.input_raster_paths[0]))

    def browse_output_dir(self):
        dirpath = filedialog.askdirectory(title="Select Output Directory")
        if dirpath:
            self.output_dir_var.set(dirpath)

    def log(self, message):
        self.log_text.configure(state='normal')
        self.log_text.insert(tk.END, str(message) + '\n')
        self.log_text.configure(state='disabled')
        self.log_text.see(tk.END)

    def process_log_queue(self):
        try:
            while True: 
                msg = self.log_queue.get_nowait()
                if msg == "PROCESS_COMPLETE_SUCCESS":
                    self.run_button.config(state=tk.NORMAL)
                    self.log(">>> Process completed successfully!")
                    messagebox.showinfo("Success", "Vectorization process completed successfully!")
                elif msg == "PROCESS_COMPLETE_FAILURE":
                    self.run_button.config(state=tk.NORMAL)
                    self.log(">>> Process failed or completed with errors.")
                    messagebox.showerror("Failure", "Vectorization process failed or completed with errors. Check log.")
                else:
                    self.log(msg)
        except queue.Empty:
            pass
        finally:
            self.master.after(100, self.process_log_queue)

    def validate_inputs(self):
        # MODIFIED: Validate list of input rasters
        if not self.input_raster_paths:
            messagebox.showerror("Input Error", "Please select one or more input raster files.")
            return False
        for path in self.input_raster_paths:
            if not os.path.isfile(path):
                messagebox.showerror("Input Error", f"Invalid input raster file: {path}")
                return False
        
        if not self.output_dir_var.get():
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
            if not messagebox.askyesno("Filename Warning", "Output filename does not end with '.gpkg'.\nThis might cause issues with GeoPackage drivers.\nContinue anyway?"):
                return False
        try:
            float(self.simplify_bldg_var.get())
            float(self.min_area_bldg_var.get())
            float(self.simplify_road_var.get())
            float(self.min_area_road_var.get())
            int(self.smooth_roads_chaikin_var.get())

            if any(v.get() < 0 for v in [self.simplify_bldg_var, self.min_area_bldg_var,
                                          self.simplify_road_var, self.min_area_road_var, self.smooth_roads_chaikin_var]):
                raise ValueError("Numeric parameters cannot be negative.")
            if not (0 <= self.conf_thresh_bldg_var.get() <= 100):
                raise ValueError("Building confidence threshold must be between 0 and 100.")
            if not (0 <= self.conf_thresh_road_var.get() <= 100):
                raise ValueError("Road confidence threshold must be between 0 and 100.")
        except ValueError as e:
            messagebox.showerror("Input Error", f"Invalid numeric input: {e}\nPlease enter valid numbers.")
            return False
        return True

    def start_processing(self):
        if not self.validate_inputs():
            return

        self.log_text.configure(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state='disabled')
        self.log("Starting processing thread...")
        self.master.update_idletasks()

        params = {
            'input_rasters': self.input_raster_paths, # MODIFIED: Pass list of paths
            'output_dir': self.output_dir_var.get(),
            'output_name': self.output_name_var.get(),
            'force': self.force_overwrite_var.get(),
            'conf_thresh_bldg_pct': self.conf_thresh_bldg_var.get(),
            'simplify_bldg': self.simplify_bldg_var.get(),
            'min_area_bldg': self.min_area_bldg_var.get(),
            'conf_thresh_road_pct': self.conf_thresh_road_var.get(),
            'simplify_road': self.simplify_road_var.get(),
            'min_area_road': self.min_area_road_var.get(),
            'smooth_roads_chaikin': self.smooth_roads_chaikin_var.get(),
        }
        self.run_button.config(state=tk.DISABLED)
        self.processing_thread = threading.Thread(
            target=run_processing,
            args=(params, self.log_queue),
            daemon=True
        )
        self.processing_thread.start()

# --- Main Execution ---
if __name__ == "__main__":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except ImportError: pass
    except AttributeError: pass
    
    root = tk.Tk()
    app = VectorizationApp(root)
    root.mainloop()