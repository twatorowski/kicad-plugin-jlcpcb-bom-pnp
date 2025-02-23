
import pcbnew
import os
import wx

# import all functions that process the board
from .logic import *


class Action(pcbnew.ActionPlugin):
    # setup default values
    def defaults(self):
        # setup the defaults
        self.name = "JLC BOM & PNP"
        self.category = "A descriptive category name"
        self.description = "A description of the plugin"

        # get the path of the plugin
        plugin_path = os.path.dirname(__file__)

        # show the button on the toolbar
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(plugin_path, 'icon.png')


    # action execution
    def Run(self):

        # get the path of the plugin
        plugin_path = os.path.dirname(__file__)

        # load the board
        board = pcbnew.GetBoard()

        # get the path to the board
        board_path = board.GetFileName()
        # get the directory name
        board_dirname = os.path.dirname(board_path)
        # get the base part of the file
        board_filename_base =  os.path.splitext(os.path.basename(board_path))[0]

        # bom and pick n place files
        bom_path = os.path.join(board_dirname,
            f'{board_filename_base}-bom-jlcpcb.csv')
        pnp_path = os.path.join(board_dirname,
            f'{board_filename_base}-pnp-jlcpcb.csv')


        # get the offset for the component placement
        drill_place_offset = get_board_drill_place_offset(board)
        # build up the component dictionary
        components = build_component_dict(board)
        # do the grouping of the components based on certain fields
        groups = group_components(components, ['MPN'])

        # generate bom lines (jlcpcb)
        header_line, bom_lines = generate_bom_list(groups, {
                'Value': None,
                '$REF': 'Designator',
                'Footprint':None,
                'DPN': 'LCSC#'
            }, filter_func=lambda c: c.get('Distributor', '').lower() == 'jlcpcb' and
                not c['_'].IsDNP()
        )
        # dump to csv
        dump_csv(bom_path, header_line, bom_lines, write_header=True)


        # load the correction data for the jlcpcb
        pnp_correction = load_pnp_correction_data(os.path.join(plugin_path,
            'jlcpcb-pnp-correction.csv'))
        # generate pnp file with correction for jlcpcb component placement offsets
        header_line, jlcpcb_pnp_lines = generate_pnp_list(components, {
                'Reference': 'Designator',
                '$X' : 'Mid X',
                '$Y' : 'Mid Y',
                '$SIDE': 'Layer',
                '$ROT': 'Rotation',
            }, filter_func=lambda c: c.get('Distributor', '').lower() == 'jlcpcb',
            pnp_correction=pnp_correction,
            global_offset=drill_place_offset,
            negate_y=True
        )
        # dump to csv
        dump_csv(pnp_path, header_line, jlcpcb_pnp_lines,
            write_header=True)


        # The entry function of the plugin that is executed on user action
        wx.MessageBox("PNP and BOM files generated successfully!", self.name,
            wx.OK | wx.ICON_INFORMATION)