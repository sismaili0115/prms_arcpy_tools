#--------------------------------
# Name:         stream_parameters.py
# Purpose:      GSFLOW stream parameters
# Notes:        ArcGIS 10.2 Version
# Author:       Charles Morton
# Created       2016-02-26
# Python:       2.7
#--------------------------------

import argparse
from collections import defaultdict
import ConfigParser
import datetime as dt
import logging
import os
# import re
import shutil
import subprocess
import sys
# from time import clock, sleep

import arcpy
from arcpy import env
from arcpy.sa import *

# import numpy as np

from support_functions import *


def stream_parameters(config_path, overwrite_flag=False, debug_flag=False):
    """Calculate PRMS Stream Parameters

    Args:
        config_file (str): Project config file path
        ovewrite_flag (bool): if True, overwrite existing files
        debug_flag (bool): if True, enable debug level logging

    Returns:
        None
    """

    # Initialize hru_parameters class
    hru = HRUParameters(config_path)

    # Log DEBUG to file
    log_file_name = 'stream_parameters_log.txt'
    log_console = logging.FileHandler(
        filename=os.path.join(hru.log_ws, log_file_name), mode='w')
    log_console.setLevel(logging.DEBUG)
    log_console.setFormatter(logging.Formatter('%(message)s'))
    logging.getLogger('').addHandler(log_console)
    logging.info('\nGSFLOW Stream Parameters')


    # check the polygon path
    hru.check_polygon_path()
    
    # read the stream parameters
    hru.read_stream_parameters()
    
    # Input folders
    stream_temp_ws = os.path.join(hru.param_ws, 'stream_rasters')
    if not os.path.isdir(stream_temp_ws):
        os.mkdir(stream_temp_ws)
        
    # Layers
    hru_polygon_lyr = 'hru_polygon_lyr'
    
    # Set ArcGIS environment variables
    arcpy.CheckOutExtension('Spatial')
    env.overwriteOutput = True
    # env.pyramid = 'PYRAMIDS -1'
    env.pyramid = 'PYRAMIDS 0'
    env.workspace = stream_temp_ws
    env.scratchWorkspace = hru.scratch_ws

    # Add fields if necessary to the HRU
    logging.info('\nAdding fields if necessary')
    add_field_func(hru.polygon_path, hru.hru_segment, 'LONG')
    add_field_func(hru.streams_path, hru.k_coef, 'DOUBLE')
    add_field_func(hru.streams_path, hru.obsin_segment, 'LONG')
    add_field_func(hru.streams_path, hru.tosegment, 'LONG')
    add_field_func(hru.streams_path, hru.x_coef, 'DOUBLE')
    
    # add some to the stream shapefile
    length_field = 'LENGTH'
    add_field_func(hru.stream_path, hru.tosegment, 'LONG')
    add_field_func(hru.stream_path, length_field, 'DOUBLE')

    # Calculate the TOSEGMENT
    logging.info("\nCalculating tosegment parameter")
    stream_segments = arcpy.da.UpdateCursor(hru.stream_path, ["OBJECTID","to_node", "tosegment"])
    compare_stream_segments = arcpy.da.SearchCursor(hru.stream_path, ["OBJECTID","from_node"])

    #Set all tosegment to zero
    for stream in stream_segments:
        stream[2] = 0   
        stream_segments.updateRow(stream)
    stream_segments.reset()
    #Search for stream's whose from_nodes match another stream's to_node
    for stream in stream_segments:
        to_node = stream[1] #to_node value
        #While compare_stream exists, Cursor.next() returns none when end of a list occurs
        for compare in compare_stream_segments:
            if to_node == compare[1]:  #compare to _node to from_node
                stream[2] = compare[0] # tosegment = compare stream objectid
                #print stream[1],compare[1], stream[2], compare[0]
                break 
        stream_segments.updateRow(stream)
        compare_stream_segments.reset()
    
    #Delete the structures created for generating the stream tosegment parameter
    del stream_segments, compare_stream_segments, stream, compare
          

    # Get stream length for each cell
#     logging.info("Stream length")
#     arcpy.MakeFeatureLayer_management(hru.polygon_path, hru_polygon_lyr)
#     arcpy.SelectLayerByAttribute_management(
#         hru_polygon_lyr, "NEW_SELECTION",
#         ' \"{0}\" = 1 And "{1}" != 0'.format(hru.type_field, hru.iseg_field))
#     length_path = os.path.join('in_memory', 'length')
#     arcpy.Intersect_analysis(
#         [hru_polygon_lyr, hru.streams_path],
#         length_path, "ALL", "", "LINE")
#     arcpy.Delete_management(hru_polygon_lyr)
#      
#     
#     arcpy.CalculateField_management(
#         hru.stream_path, length_field, '!shape.length@meters!', "PYTHON")
#     length_dict = defaultdict(int)
#      
#         # DEADBEEF - This probably needs a maximum limit
#     for row in arcpy.da.SearchCursor(
#         length_path, [hru.id_field, length_field]):
#         length_dict[int(row[0])] += int(row[1])
#     fields = [hru.type_field, hru.iseg_field, hru.rchlen_field, hru.id_field]
#     with arcpy.da.UpdateCursor(hru.polygon_path, fields) as update_c:
#         for row in update_c:
#             if (int(row[0]) == 1 and int(row[1]) != 0):
#                 row[2] = length_dict[int(row[3])]
#             else:
#                 row[2] = 0
#             update_c.updateRow(row)
#     del length_dict, length_field, fields, hru_polygon_lyr

    # Get list of segments and downstream cell for each stream/lake cell
    # Downstream is calulated from flow direction
    # Use IRUNBOUND instead of ISEG, since ISEG will be zeroed for lakes
    logging.info("Cell out-flow dictionary")
    cell_dict = dict()
    fields = [
        hru.type_field, hru.krch_field, hru.lake_id_field, hru.iseg_field,
        hru.irunbound_field, hru.subbasin_field, hru.dem_adj_field,
        hru.flow_dir_field, hru.id_field]
#         hru.flow_dir_field, hru.col_field, hru.row_field, hru.id_field]
    for row in arcpy.da.SearchCursor(hru.polygon_path, fields):
        # Skip inactive cells
        if int(row[0]) == 0:
            continue
        # DEADBEEF
        # Skip cells flowing to inactive water
        # elif int(row[0]) == 3:
        #    continue
        # Skip if not lake and not stream
        elif (int(row[1]) == 0 and int(row[2]) == 0):
            continue
        # Read in parameters
        cell = (int(row[8]), int(row[9]))
        # next_row_col(FLOW_DIR, CELL)
        # HRU_ID, ISEG,  NEXT_CELL, DEM_ADJ, X, X, X
        cell_dict[cell] = [
            int(row[10]), int(row[4]), next_row_col(int(row[7]), cell),
            float(row[6]), 0, 0, 0]
        del cell
    # Build list of unique segments
    iseg_list = sorted(list(set([v[1] for v in cell_dict.values()])))


    # Calculate IREACH and OUTSEG
    logging.info("Calculate IREACH and OUTSEG")
    outseg_dict = dict()
    for iseg in sorted(iseg_list):
        logging.debug("    Segment: {0}".format(iseg))
        # Subset of cell_dict for current iseg
        iseg_dict = dict(
            [(k, v) for k, v in cell_dict.items() if v[1] == iseg])
        # List of all cells in current iseg
        iseg_cells = iseg_dict.keys()
        # List of out_cells for all cells in current iseg
        out_cells = [value[2] for value in iseg_dict.values()]
        # Every iseg will (should?) have one out_cell
        out_cell = list(set(out_cells)-set(iseg_cells))

        # Process streams and lakes separately
        # Streams
        if iseg > 0:
            # If there is more than one out_cell
            #   there is a problem with the stream network
            if len(out_cell) != 1:
                logging.error(
                    ('\nERROR: ISEG {0} has more than one out put cell' +
                     '\n  Out cells: {1}' +
                     '\n  Check for streams exiting then re-entering a lake' +
                     '\n  Lake cell elevations may not be constant\n').format(
                         iseg, out_cell))
                sys.exit()
            # If not output cell, assume edge of domain
            try:
                outseg = cell_dict[out_cell[0]][1]
            except KeyError:
                outseg = exit_seg

            # Track sub-basin outseg
            outseg_dict[iseg] = outseg
            # Calculate reach number for each cell
            reach_dict = dict()
            start_cell = list(set(iseg_cells)-set(out_cells))[0]
            for i in xrange(len(out_cells)):
                # logging.debug("    Reach: {0}  Cell: {1}".format(i+1, start_cell))
                reach_dict[start_cell] = i+1
                start_cell = iseg_dict[start_cell][2]
            # For each cell in iseg, save outseg, reach, & maxreach
            for iseg_cell in iseg_cells:
                cell_dict[iseg_cell][4:] = [
                    outseg, reach_dict[iseg_cell], len(iseg_cells)]
            del reach_dict, start_cell, outseg
        # Lakes
        elif iseg < 0:
            # For lake cells, there can be multiple outlets if all of them
            #   are to inactive cells or out of the model
            # Otherwise, like streams, there should only be one outcell per iseg
            if len(out_cell) == 1:
                try:
                    outseg = cell_dict[out_cell[0]][1]
                except KeyError:
                    outseg = exit_seg
            elif (len(out_cell) != 1 and
                  all(x[0] not in cell_dict.keys() for x in out_cell)):
                outseg = exit_seg
                logging.debug(
                    ('  All out cells are inactive, setting outseg ' +
                     'to exit_seg {}').format(exit_seg))
            else:
                logging.error(
                    ('\nERROR: ISEG {0} has more than one out put cell' +
                     '\n  Out cells: {1}' +
                     '\n  Check for streams exiting then re-entering a lake' +
                     '\n  Lake cell elevations may not be constant\n').format(
                         iseg, out_cell))
            # Track sub-basin outseg
            outseg_dict[iseg] = outseg
            # For each lake segment cell, only save outseg
            # All lake cells are routed directly to the outseg
            for iseg_cell in iseg_cells:
                cell_dict[iseg_cell][4:] = [outseg, 0, 0]
            del outseg
        del iseg_dict, iseg_cells, iseg
        del out_cells, out_cell

    # Calculate stream elevation
    logging.info("Stream elevation (DEM_ADJ - 1 for now)")
    fields = [
            hru.type_field, hru.iseg_field, hru.dem_adj_field,
            hru.strm_top_field]
    with arcpy.da.UpdateCursor(hru.polygon_path, fields) as update_c:
        for row in update_c:
            if int(row[0]) == 1 and int(row[1]) != 0:
                row[3] = float(row[2]) - 1
            else:
                row[3] = 0
            update_c.updateRow(row)

    # Saving ireach and outseg
    logging.info("Save IREACH and OUTSEG")
    fields = [
        hru.type_field, hru.iseg_field, hru.row_field,
        hru.outseg_field, hru.reach_field, hru.maxreach_field]
    with arcpy.da.UpdateCursor(hru.polygon_path, fields) as update_c:
        for row in update_c:
            # if (int(row[0]) > 0 and int(row[1]) > 0):
            # DEADBEEF - I'm not sure why only iseg > 0 in above line
            # DEADBEEF - This should set outseg for streams and lakes
            if (int(row[0]) > 0 and int(row[1]) != 0):
                row[4:] = cell_dict[(int(row[2]), int(row[3]))][4:]
            else:
                row[4:] = [0, 0, 0]
            update_c.updateRow(row)

    # Calculate IUPSEG for all segments flowing out of lakes
    logging.info("IUPSEG for streams flowing out of lakes")
    upseg_dict = dict(
        [(v, k) for k, v in outseg_dict.iteritems() if k < 0])
    fields = [hru.type_field, hru.iseg_field, hru.iupseg_field]
    with arcpy.da.UpdateCursor(hru.polygon_path, fields) as update_c:
        for row in update_c:
            if (int(row[0]) == 1 and int(row[1]) != 0 and
                int(row[1]) in upseg_dict.keys()):
                row[2] = upseg_dict[int(row[1])]
            else:
                row[2] = 0
            update_c.updateRow(row)

    # Build dictionary of which segments flow into each segment
    # Used to calculate seg-basins (sub watersheds) for major streams
    # Also save list of all segments that pour to exit
    logging.info("Segment in/out-flow dictionary")
    inseg_dict = defaultdict(list)
    pourseg_dict = dict()
    pourseg_list = []
    for key, value in outseg_dict.iteritems():
        if key == exit_seg:
            continue
            # inseg_dict[key].append(key)
        elif value == exit_seg:
            pourseg_list.append(key)
            inseg_dict[key].append(key)
        else:
            inseg_dict[value].append(key)

    # Update pourseg for each segment, working up from initial pourseg
    # Pourseg is the final exit segment for each upstream segment
    for pourseg in pourseg_list:
        testseg_list = inseg_dict[pourseg]
        while testseg_list:
            testseg = testseg_list.pop()
            pourseg_dict[testseg] = pourseg
            if pourseg == testseg:
                continue
            testseg_list.extend(inseg_dict[testseg])
        del testseg_list

    # Calculate SEG_BASIN for all active cells
    # SEG_BASIN corresponds to the ISEG of the lowest segment
    logging.info("SEG_BASIN")
    fields = [hru.type_field, hru.irunbound_field, hru.segbasin_field]
    with arcpy.da.UpdateCursor(hru.polygon_path, fields) as update_c:
        for row in update_c:
            if int(row[0]) > 0 and int(row[1]) != 0:
                row[2] = pourseg_dict[int(row[1])]
            else:
                row[2] = 0
            update_c.updateRow(row)

    # Set all lake iseg to 0
    logging.info("Lake ISEG")
    update_rows = arcpy.UpdateCursor(hru.polygon_path)
    for row in update_rows:
        if int(row.getValue(hru.type_field)) != 2:
            continue
        iseg = int(row.getValue(hru.iseg_field))
        if iseg < 0:
            row.setValue(hru.iseg_field, 0)
        update_rows.updateRow(row)
        del row, iseg
    del update_rows

    # Set environment parameters
    env.extent = hru.extent
    env.cellsize = hru.cs
    env.outputCoordinateSystem = hru.sr

    # Build rasters
    if output_rasters_flag:
        logging.info("\nOutput model grid rasters")
        arcpy.PolygonToRaster_conversion(
            hru.polygon_path, hru.type_field, hru_type_raster,
            "CELL_CENTER", "", hru.cs)
        arcpy.PolygonToRaster_conversion(
            hru.polygon_path, hru.dem_adj_field, dem_adj_raster,
            "CELL_CENTER", "", hru.cs)
        arcpy.PolygonToRaster_conversion(
            hru.polygon_path, hru.iseg_field, iseg_raster,
            "CELL_CENTER", "", hru.cs)
        arcpy.PolygonToRaster_conversion(
            hru.polygon_path, hru.irunbound_field, irunbound_raster,
            "CELL_CENTER", "", hru.cs)
        arcpy.PolygonToRaster_conversion(
            hru.polygon_path, hru.segbasin_field, segbasin_raster,
            "CELL_CENTER", "", hru.cs)
        arcpy.PolygonToRaster_conversion(
            hru.polygon_path, hru.subbasin_field, subbasin_raster,
            "CELL_CENTER", "", hru.cs)

    # Build rasters
    if output_ascii_flag:
        logging.info("Output model grid ascii")
        arcpy.RasterToASCII_conversion(hru_type_raster, hru_type_ascii)
        arcpy.RasterToASCII_conversion(dem_adj_raster, dem_adj_ascii)
        arcpy.RasterToASCII_conversion(iseg_raster, iseg_ascii)
        arcpy.RasterToASCII_conversion(irunbound_raster, irunbound_ascii)
        arcpy.RasterToASCII_conversion(segbasin_raster, segbasin_ascii)
        arcpy.RasterToASCII_conversion(subbasin_raster, subbasin_ascii)
        sleep(5)

    # Input parameters files for Cascade Routing Tool (CRT)
    logging.info("\nOutput CRT files")

    # Generate STREAM_CELLS.DAT file for CRT
    logging.info("  {0}".format(
        os.path.basename(crt_stream_cells_path)))
    stream_cells_list = []
    fields = [
        hru.type_field, hru.iseg_field, hru.reach_field,
        hru.col_field, hru.row_field]
    for row in arcpy.da.SearchCursor(hru.polygon_path, fields):
        if int(row[0]) == 1 and int(row[1]) > 0:
            stream_cells_list.append(
                [int(row[4]), int(row[3]), int(row[1]), int(row[2]), 1])
    if stream_cells_list:
        with open(crt_stream_cells_path, 'w+') as f:
            f.write('{0}    NREACH\n'.format(len(stream_cells_list)))
            for stream_cells_l in sorted(stream_cells_list):
                f.write(' '.join(map(str, stream_cells_l))+'\n')
        f.close
    del stream_cells_list

    # Generate OUTFLOW_HRU.DAT for CRT
    # Outflow cells exit the model to inactive cells or out of the domain
    #   Outflow field is set in dem_2_streams
    logging.info("  {0}".format(
        os.path.basename(crt_outflow_hru_path)))
    outflow_hru_list = []
    fields = [
        hru.type_field, hru.outflow_field, hru.subbasin_field,
        hru.row_field, hru.col_field]
    for row in arcpy.da.SearchCursor(hru.polygon_path, fields):
        if int(row[0]) != 0 and int(row[1]) == 1:
            outflow_hru_list.append([int(row[3]), int(row[4])])
    if outflow_hru_list:
        with open(crt_outflow_hru_path, 'w+') as f:
            f.write('{0}    NUMOUTFLOWHRU\n'.format(
                len(outflow_hru_list)))
            for i, outflow_hru in enumerate(outflow_hru_list):
                f.write('{0} {1} {2}   OUTFLOW_ID ROW COL\n'.format(
                    i+1, outflow_hru[0], outflow_hru[1]))
        f.close()
    del outflow_hru_list

    #  Generate OUTFLOW_HRU.DAT for CRT
    # logging.info("  {0}".format(
    #    os.path.basename(crt_outflow_hru_path)))
    # outflow_hru_list = []
    # fields = [
    #    hru.type_field, hru.iseg_field, hru.outseg_field, hru.reach_field,
    #    hru.maxreach_field, hru.col_field, hru.row_field]
    # for row in arcpy.da.SearchCursor(hru.polygon_path, fields):
    #    if int(row[0]) != 1 or int(row[1]) == 0: continue
    #    if int(row[2]) == 0 and int(row[3]) == int(row[4]):
    #        outflow_hru_list.append([int(row[6]), int(row[5])])
    # if outflow_hru_list:
    #    with open(crt_outflow_hru_path, 'w+') as f:
    #        f.write('{0}    NUMOUTFLOWHRU\n'.format(
    #            len(outflow_hru_list)))
    #        for i, outflow_hru in enumerate(outflow_hru_list):
    #            f.write('{0} {1} {2}   OUTFLOW_ID ROW COL\n'.format(
    #                i+1, outflow_hru[0], outflow_hru[1]))
    #    f.close()
    # del outflow_hru_list

    # Generate HRU_CASC.DAT for CRT
    logging.info("  {0}".format(os.path.basename(crt_hru_casc_path)))
    with open(hru_type_ascii, 'r') as f:
        ascii_data = f.readlines()
    f.close()
    hru_casc_header = (
        '{0} {1} {2} {3} {4} {5} {6} {7}     ' +
        'HRUFLG STRMFLG FLOWFLG VISFLG ' +
        'IPRN IFILL DPIT OUTITMAX\n').format(
            crt_hruflg, crt_strmflg, crt_flowflg, crt_visflg,
            crt_iprn, crt_ifill, crt_dpit, crt_outitmax)
    with open(crt_hru_casc_path, 'w+') as f:
        f.write(hru_casc_header)
        for ascii_line in ascii_data[6:]:
            f.write(ascii_line)
    f.close()
    del hru_casc_header, ascii_data

    # Generate LAND_ELEV.DAT for CRT
    logging.info("  {0}".format(os.path.basename(crt_land_elev_path)))
    with open(dem_adj_ascii, 'r') as f:
        ascii_data = f.readlines()
    f.close()
    with open(crt_land_elev_path, 'w+') as f:
        f.write('{0} {1}       NROW NCOL\n'.format(
            ascii_data[1].split()[1], ascii_data[0].split()[1]))
        for ascii_line in ascii_data[6:]:
            f.write(ascii_line)
    f.close()
    del ascii_data

    # Generate XY.DAT for CRT
    logging.info("  {0}".format(os.path.basename(crt_xy_path)))
    xy_list = [
        map(int, row)
        for row in sorted(arcpy.da.SearchCursor(
            hru.polygon_path, [hru.id_field, hru.x_field, hru.y_field]))]
    with open(crt_xy_path, 'w+') as f:
        for line in sorted(xy_list):
            f.write(' '.join(map(str, line))+'\n')
    f.close()

    # Run CRT
    logging.info('\nRunning CRT')
    os.chdir(crt_ws)
    subprocess.check_call(crt_exe_name)
    os.chdir(hru.param_ws)

    # Read in outputstat.txt to check for errors
    logging.info("\nReading CRT {0}".format(output_name))
    output_path = os.path.join(crt_ws, output_name)
    with open(output_path, 'r') as f:
        output_data = [l.strip() for l in f.readlines()]
    f.close()

    # Check if there are
    if 'CRT FOUND UNDECLARED SWALE HRUS' in output_data:
        logging.error(
            '\nERROR: CRT found undeclared swale HRUs (sinks)\n' +
            '  All sinks must be filled before generating cascades\n' +
            '  Check the CRT outputstat.txt file\n')
        sys.exit()


def cell_distance(cell_a, cell_b, cs):
    """"""
    ai, aj = cell_a
    bi, bj = cell_b
    return math.sqrt((ai - bi) ** 2 + (aj - bj) ** 2) * cs

# def calc_stream_width(flow_acc):
#    return -2E-6 * flow_acc ** 2 + 0.0092 * flow_acc + 1


def arg_parse():
    """"""
    parser = argparse.ArgumentParser(
        description='Stream Parameters',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        '-i', '--ini', required=True,
        help='Project input file', metavar='PATH')
    parser.add_argument(
        '-o', '--overwrite', default=False, action="store_true",
        help='Force overwrite of existing files')
    parser.add_argument(
        '--debug', default=logging.INFO, const=logging.DEBUG,
        help='Debug level logging', action="store_const", dest="loglevel")
    args = parser.parse_args()

    # Convert input file to an absolute path
    if os.path.isfile(os.path.abspath(args.ini)):
        args.ini = os.path.abspath(args.ini)
    return args


if __name__ == '__main__':
    args = arg_parse()

    logging.basicConfig(level=args.loglevel, format='%(message)s')
    logging.info('\n{0}'.format('#'*80))
    log_f = '{0:<20s} {1}'
    logging.info(log_f.format('Run Time Stamp:', dt.datetime.now().isoformat(' ')))
    logging.info(log_f.format('Current Directory:', os.getcwd()))
    logging.info(log_f.format('Script:', os.path.basename(sys.argv[0])))

    # Calculate GSFLOW Stream Parameters
    stream_parameters(
        config_path=args.ini, overwrite_flag=args.overwrite,
        debug_flag=args.loglevel==logging.DEBUG)
