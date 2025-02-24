import csv
import re
import math
import pcbnew

# returns the offset for drill and place
def get_board_drill_place_offset(board: pcbnew.BOARD):
    # return the offset vector in mm
    return pcbnew.ToMM(board.GetDesignSettings().GetAuxOrigin())


# function for sorting the references
def sorting_key_for_references(ref:str):
    # parse the reference
    if not (m := re.match(r"^([^0-9]+)([0-9]{1,5})$", ref)):
        raise ValueError(f"Invalid reference: {ref}")
    # get the values for the parts of the designators
    letters, digits = m[1], m[2]
    # return the string in format C1 -> C00001 which is "sortable".
    # otherwise things like C2 falling behing C19 would occur.
    return letters + '0' * (5 - len(digits)) + digits


# builds up the component dictionary
def build_component_dict(board: pcbnew.BOARD):
    # component dictionary
    comps = {}

    # build up the array of all components
    for fp in board.Footprints():
        # get the value of the reference field
        ref = fp.Reference().GetText()
        # sanity check
        if ref in comps:
            raise Exception(f'Duplicate component reference found {ref}')
        # append to the dictionary
        comps[ref] = fp.GetFieldsText()
        # store the reference to the component itself
        comps[ref]['_'] = fp
    # return the component dictionary
    return comps


# do the grouping of the components based on certain fields
def group_components(components: dict, group_by: list[str]):
    # this will hold the groups of components that have the same group by value
    group_vals = {}
    # scan across the components
    for ref, vals in components.items():
        # get the grouping value
        group_val = ", ".join([vals.get(vname, '') for vname in group_by])
        # create a placeholder
        if group_val not in group_vals:
            group_vals[group_val] = []
        # append the component to the group
        group_vals[group_val].append(ref)

    # return the groups
    return {", ".join(refs): [components[ref] for ref in refs]
        for refs in group_vals.values() }


# genetare a bom list
def generate_bom_list(component_groups: dict, headers: dict[str, str],
    filter_func = None):
    # this will hold all the lines of the bom
    lines = []
    # generate header line
    header_line = [hdr_name or hdr for hdr, hdr_name in headers.items()]

    # one group is one line
    for components in component_groups.values():
        # filter out components that are not in bom
        components = [c for c in components if not c['_'].IsExcludedFromBOM()]
        # filter out components that did not pass filtering
        if filter_func is not None:
            components = [c for c in components if filter_func(c)]
        # get the quantity
        qty = len(components)
        # well, 0 instances of this component
        if not qty:
            continue

        # sort the components
        components = sorted(components,
            key=lambda x: sorting_key_for_references(x['Reference']))
        # get the references
        references = ",".join([c['Reference'] for c in components])

        # this will hold the line (love is not always on timeee! whou whou whou!
        # [by Toto]) contnents
        line = {}
        # go though the headers
        for hdr, hdr_name in headers.items():
            # use the header name if no alternative was provided
            hdr_name = hdr_name or hdr
            # quantity
            if hdr == '$QTY':
                line[hdr_name] = qty
            # reference
            elif hdr == '$REF':
                line[hdr_name] = references
            # all other fields
            else:
                unique_values = set([c.get(hdr, '') for c in components])
                # produce comma separated list of unique values
                line[hdr_name] = ",".join(unique_values)
        # store the sorting val
        line['$SORT'] = sorting_key_for_references(components[0]['Reference'])
        # append to the list of all lines
        lines.append(line)

    # now let's sort the lines
    lines = sorted(lines, key=lambda x: x['$SORT'])

    # return all the lines
    return header_line, lines


# dump data to csv
def dump_csv(fname: str, headers: list[str], values:list[dict],
    write_header:bool = True):
    # open the file
    with open(fname, "w") as f:
        # initiate the dict writer
        writer = csv.DictWriter(f, headers, extrasaction='ignore')
        if write_header:
            writer.writeheader()
        # write all the rows
        writer.writerows(values)

# load the csv file
def load_csv(fname: str, headers: list | None = None):
    # load the file
    with open(fname, "r") as f:
        # filter out the comments
        reader = csv.DictReader(filter(lambda row: row.strip() and
            not row.lstrip().startswith("#"), f), headers,
            skipinitialspace=True)
        # enclose the result in a list
        lines = list(reader)
        # store the header line
        if headers is None:
            headers = list(reader.fieldnames)

    # return the values read
    return headers, lines

# laod the pnp correction data from the csv
def load_pnp_correction_data(fname: str):
    # load data from the csv
    headers, lines = load_csv(fname)
    # turn into a dict indexable by the footprint name
    return { l['Footprint']: l for l in lines if 'Footprint' in l }


# generate a list of lines for the pick and place
def generate_pnp_list(components: dict, headers: dict[str, str],
    filter_func = None, pnp_correction:dict = None, output_funcs = None,
    global_offset: tuple[float, float] | None = None,
    negate_y:bool = False):
    # this will hold the lines
    lines = []
    # generate header line
    header_line = [hdr_name or hdr for hdr, hdr_name in headers.items()]

    # go through all of the components
    for ref, comp in components.items():
        # get the component object
        c = comp['_']
        # component shall not be placed
        if c.IsDNP() or c.IsExcludedFromPosFiles():
            continue
        # component was filtered out
        if filter_func is not None and not filter_func(comp):
            continue

        # get item position
        vec = c.GetPosition()
        # extract coordinates, convert to mm
        x, y = pcbnew.ToMM(vec.x), pcbnew.ToMM(vec.y)
        # get the orientation
        rot = c.GetOrientationDegrees() % 360

        # global offsets
        if global_offset is not None:
            x -= global_offset[0]
            y -= global_offset[1]

        # got correction data for this footprint?
        if pnp_correction:
            # rotation and offset entry
            corr = None
            # do we have an exact match in footprint name?
            if comp['Footprint'] in pnp_correction:
                corr = pnp_correction[comp['Footprint']]
            # check for lib-less footprint name match
            else:
                # ':' is the library name delimiter
                lib_name = comp['Footprint'].split(':')
                # library-less footprint name specified?
                if len(lib_name) == 2 and lib_name[1] in pnp_correction:
                    corr = pnp_correction[lib_name[1]]
            # extract the data
            if corr:
                # load position offsets
                xo, yo = float(corr.get('X', 0)), float(corr.get('Y', 0))
                # load rotation correction
                rot_c = float(corr.get('Rotation'))
                # update rotation
                rot = (rot + rot_c) % 360
                # got the rotation, apply it to offset
                if rot:
                    xo = xo * math.cos(math.radians(rot))
                    yo = yo * math.sin(math.radians(rot))
                # use the offset to update the position and orientation
                x += xo
                y += yo

        # y coordinate negation
        if negate_y:
            y = -y


        # this will hold the line (love is not always on timeee! whou whou whou!
        # [by Toto]) contnents
        line = {}
        # go though the headers
        for hdr, hdr_name in headers.items():
            # use the header name if no alternative was provided
            hdr_name = hdr_name or hdr
            # x coordinate
            if hdr == '$X':
                value = round(x, 3)
            # y coordinate
            elif hdr == '$Y':
                value = round(y, 3)
            # rotation
            elif hdr == '$ROT':
                value = rot
            # reference
            elif hdr == '$SIDE':
                value = 'T' if c.GetSide() == 0 else 'B'
            # all other fields
            else:
                # produce comma separated list of unique values
                value = comp.get(hdr)
            # output modifier?
            if output_funcs is not None and (f := output_funcs.get(hdr_name)):
                value = f(value)
            # store the line value
            line[hdr_name] = value
        # store the sorting val
        line['$SORT'] = sorting_key_for_references(ref)
        # append to the list of all lines
        lines.append(line)

    # now let's sort the lines
    lines = sorted(lines, key=lambda x: x['$SORT'])

    # return all the lines
    return header_line, lines
