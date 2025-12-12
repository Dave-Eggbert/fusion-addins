import sys, os
current_dir = os.path.dirname(__file__)
parent_dir = os.path.dirname(current_dir)
shared_folder = os.path.join(parent_dir, "SharedUtils")
if current_dir not in sys.path: sys.path.append(current_dir)
if shared_folder not in sys.path: sys.path.append(shared_folder)
import CustomComputeFeature, Inputs, utils, Combine
import adsk.core, adsk.fusion
from adsk.core import Point3D, Vector3D
import math
from dataclasses import dataclass
from typing import cast
utils.misc.force_reload_modules('CustomComputeFeature', 'Inputs', 'utils', 'Combine')


_feature: CustomComputeFeature.CustomComputeFeature

def run(context):
    global _feature
    _feature = PatternCutout()

def stop(context):
    global _feature
    del _feature

class PatternInputs(Inputs.Inputs):
    class Types:
        TRIANGLES = Inputs.DropDownInput.Item('Triangles', 0)
        RHOMBUSES = Inputs.DropDownInput.Item('Rhombuses', 1)
        CROSS = Inputs.DropDownInput.Item('Cross', 2)
        ROUNDED_RECTANGLE = Inputs.DropDownInput.Item('Rounded Rectangle', 3)
        FROLI = Inputs.DropDownInput.Item('Froli', 4)
        ADAPTIVE = Inputs.DropDownInput.Item('Adaptive', 5)

    def __init__(self, units_manager: adsk.core.UnitsManager):
        units = units_manager.defaultLengthUnits
        self.faces = Inputs.SelectionByEntityTokenInput('faces', 'Faces', 'PlanarFaces', 1, 0, 'Select faces to create triangle pockets on.')
        self.profiles = Inputs.SelectionByEntityTokenInput('profiles', 'Profiles', 'Profiles', 0, 0, 'Select profiles on a single face to restrict the pattern to these profiles. Only makes sense if a single face is selected.')
        self.type = Inputs.DropDownInput('type', 'Type', utils.misc.class_property_values(PatternInputs.Types), PatternInputs.Types.TRIANGLES.value, 'The type of pattern to use.')
        self.preferred_width = Inputs.FloatInput('preferred_width', 'Preferred Width', 10, 'Indicates the preferred width of the shape.', units)
        self.preferred_height = Inputs.FloatInput('preferred_height', 'Preferred Height', 15, 'Indicates the preferred height of the shape.', units)
        self.spacing = Inputs.FloatInput('spacing', 'Spacing', 2, 'Spacing between the shapes.', units)
        self.inset = Inputs.FloatInput('inset', 'Inset', 2, 'Inset of the pattern from the face\'s edges', units)
        self.inner_loop_offset = Inputs.FloatInput('inner_loop_offset', 'Inner Loop Offset', 2, 'Material to keep around the inner loop of the face', units)
        self.fillet = Inputs.FloatInput('fillet', 'Fillet', 0.8, 'Fillet radius', units)
        self.compensate_fillet = Inputs.CheckboxInput('compensate_fillet', 'Compensate Fillet', False, 'Makes all triangles in one row appear to be bottom and top aligned, irrespective of the fillet applied to the corners')
        self.adaptive = Inputs.CheckboxInput('adaptive', 'Adaptive', True, 'Prioritzes filling up the available space with the pattern over adhering to the width/height values, treating them more a starting point.')
        self.remainder = Inputs.FloatInput('remainder', 'Remaining Material', 0, 'Thickness of the remaining material to leave untouched.', units)
        super().__init__()


class PatternCutout(CustomComputeFeature.CustomComputeFeature):
    plugin_id = 'antonPatternCutouts'
    plugin_name = 'PatternCutouts'
    plugin_desc = 'Pattern Cutouts'
    plugin_tooltip = 'Creates patterned cutouts of various shapes.'
    inputs: PatternInputs

    def create_inputs(self) -> PatternInputs:
        return PatternInputs(self.app.activeProduct.unitsManager)

    def execute(self) -> list[Combine.Combine]:
        result: list[Combine.Combine] = []
        for face in cast(list[adsk.fusion.BRepFace], self.inputs.faces.value):
            shape = self.create_pattern_for_face(face, cast(list[adsk.fusion.Profile], self.inputs.profiles.value))
            result.append(Combine.Combine(face.body, shape, Combine.Operation.CUT))
        return result
    
    def input_changed(self, input):
        if input.id == self.inputs.type.id:
            self.inputs.profiles.input.isVisible = self.inputs.type.value != PatternInputs.Types.FROLI.value

            dimensions_enabled = self.inputs.type.value == PatternInputs.Types.TRIANGLES.value or self.inputs.type.value == PatternInputs.Types.RHOMBUSES.value
            self.inputs.preferred_width.input.isVisible = dimensions_enabled
            self.inputs.preferred_height.input.isVisible = dimensions_enabled
            self.inputs.adaptive.input.isVisible = dimensions_enabled

            self.inputs.spacing.input.isVisible = dimensions_enabled or self.inputs.type.value == PatternInputs.Types.FROLI.value
            self.inputs.compensate_fillet.input.isVisible = self.inputs.type.value == PatternInputs.Types.TRIANGLES.value
            self.inputs.remainder.input.isVisible = self.inputs.type.value != PatternInputs.Types.FROLI.value

            self.inputs.inner_loop_offset.input.isVisible = self.inputs.type.value == PatternInputs.Types.ADAPTIVE.value

    def create_pattern_for_face(self, face: adsk.fusion.BRepFace, profiles: list[adsk.fusion.Profile]) -> adsk.fusion.BRepBody:
        mgr = adsk.fusion.TemporaryBRepManager.get()
        opposite_face = utils.brep.get_opposite_face(face)
        depth = abs(utils.brep.distance_along_normal_between_faces(face, opposite_face))
        depth -= self.inputs.remainder.value
        cut_normal = utils.brep.normal_towards_face(face, opposite_face)
        cut = utils.vector.scaled_by(cut_normal, depth)

        if len(profiles) > 0:
            result: adsk.fusion.BRepBody | None = None
            for profile in profiles:
                sketch = profile.parentSketch
                profile_body = mgr.copy(profile.face.body)
                mgr.transform(profile_body, utils.matrix.transform_from_root(sketch.origin, sketch.xDirection, sketch.yDirection))
                mgr.booleanOperation(profile_body, face.body, adsk.fusion.BooleanTypes.IntersectionBooleanType) # type: ignore
                profile_face = profile_body.faces[0]
                coords = utils.brep.coordinate_system_into_face(profile_face, z=cut)
                origin_on_face = utils.brep.project_point_onto_face(coords[0], face)
                coords_on_face = (origin_on_face,) + coords[1:]
                next_triangles = self.call_generator(profile_face, cut, coords_on_face)
                mgr.transform(next_triangles, utils.matrix.transform_from_root(*coords_on_face[:3]))
                if result:
                    mgr.booleanOperation(result, next_triangles, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore
                else:
                    result = next_triangles
            assert(result is not None)
            return result
        else:
            coords = utils.brep.coordinate_system_into_face(face, z=cut)
            result = self.call_generator(face, cut, coords)
            mgr.transform(result, utils.matrix.transform_from_root(*coords[:3]))
            return result
        
    def call_generator(self, face: adsk.fusion.BRepFace, cut: Vector3D, coords: tuple[Point3D, Vector3D, Vector3D, Vector3D]):
        type = self.inputs.type.value
        if type == PatternInputs.Types.TRIANGLES.value:
            return create_triangles(face, cut, self.inputs)
        elif type == PatternInputs.Types.RHOMBUSES.value:
            return create_rhombuses_from_inputs(face, cut, self.inputs)
        elif type == PatternInputs.Types.CROSS.value:
            return create_cross(face, cut, self.inputs)
        elif type == PatternInputs.Types.ROUNDED_RECTANGLE.value:
            return create_rounded_rect(face, cut, self.inputs)
        elif type == PatternInputs.Types.FROLI.value:
            return create_froli_grid(face, cut, self.inputs)
        elif type == PatternInputs.Types.ADAPTIVE.value:
            return create_adaptive(face, cut, coords, self.inputs)
        else:
            raise ValueError(f'Unknown pattern type: {type}')


def create_triangles(face: adsk.fusion.BRepFace, cut: Vector3D,  inputs: PatternInputs) -> adsk.fusion.BRepBody:
    mgr = adsk.fusion.TemporaryBRepManager.get()
    spacing = inputs.spacing.value * 2
    fillet = inputs.fillet.value
    compensate_fillet = inputs.compensate_fillet.value

    long_edge, short_edge = utils.brep.longest_and_adjecent_edge_of_face(face)
    face_length = long_edge.length
    face_width = short_edge.length
    vertical_space = face_width - 2 * inputs.inset.value
    horizontal_space = face_length - 2 * inputs.inset.value
    rows = max(1, math.floor((vertical_space + spacing/2) / (inputs.preferred_height.value + spacing/2)))
    columns = max(1, math.floor((horizontal_space + spacing) / (inputs.preferred_width.value + spacing)))
    width = inputs.preferred_width.value
    height = inputs.preferred_height.value
    ratio = width/height

    def point_angle(width, height):
        base_angle = math.atan(height/(width/2))
        return math.pi - 2 * base_angle

    def fillet_height_offset(point_angle):
        return (fillet/math.sin(point_angle/2) - fillet) if compensate_fillet else 0

    def compute_vertical_spacing(height, point_angle):
        if rows == 1:
            return 0
        return (vertical_space - rows * (height - fillet_height_offset(point_angle))) / (rows - 1)

    def visual_spacing(point_angle):
        spacing_correction = math.tan(point_angle/2) * fillet_height_offset(point_angle)
        return math.cos(point_angle/2) * (spacing/2 - spacing_correction)

    def spacing_deviation(h):
        angle = point_angle(width, h)
        return visual_spacing(angle) - compute_vertical_spacing(h, angle)

    def height_deviation(h):
        actual_height = h - fillet_height_offset(point_angle(width, h))
        return actual_height - vertical_space

    vertical_spacing = visual_spacing(point_angle(width, height))
    
    if inputs.adaptive.value:
        width = (horizontal_space - (columns - 1) * spacing) / columns
        height_lower = width/ratio * 0.5
        height_upper = width/ratio * 2
        if rows > 1:
            height = utils.misc.binary_search(height_lower, height_upper, spacing_deviation, 0, 0.1)
        else:
            height = utils.misc.binary_search(height_lower, height_upper, height_deviation, 0, 0.1)
        vertical_spacing = compute_vertical_spacing(height, point_angle(width, height))

    triangle = utils.brep.isosceles_triangle(width, height, cut.length, fillet)
    triangle_height = (triangle.boundingBox.maxPoint.y - triangle.boundingBox.minPoint.y) if compensate_fillet else height

    upside_down_triangle = mgr.copy(triangle)
    flip_transform = utils.matrix.mirror_matrix(Point3D.create(0, triangle_height/2, 0), Vector3D.create(1, -1, 1))
    mgr.transform(upside_down_triangle, flip_transform)

    row = mgr.copy(triangle)
    for idx in range(columns * 2 - 1):
        x = idx * (width + spacing) / 2
        t = mgr.copy(triangle if idx % 2 == 0 else upside_down_triangle)
        mgr.transform(t, utils.matrix.translation_matrix(Vector3D.create(x, 0, 0)))
        mgr.booleanOperation(row, t, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore

    inverted_row = mgr.copy(row)
    mgr.transform(inverted_row, flip_transform)

    result = mgr.copy(row)
    for idx in range(1, rows):
        y = idx * (triangle_height + vertical_spacing)
        r = mgr.copy(row if idx % 2 == 0 else inverted_row)
        mgr.transform(r, utils.matrix.translation_matrix(Vector3D.create(0, y, 0)))
        mgr.booleanOperation(result, r, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore

    result_bb = result.preciseBoundingBox
    offset_x = face_length/2 - (result_bb.maxPoint.x + result_bb.minPoint.x)/2
    offset_y = face_width/2 - (result_bb.maxPoint.y + result_bb.minPoint.y)/2
    mgr.transform(result, utils.matrix.translation_matrix(Vector3D.create(offset_x, offset_y, 0)))
    return result


@dataclass
class RhombusParameters:
    width: float
    height: float
    spacing: float
    inset: float
    fillet: float
    adaptive: bool

def create_rhombuses_from_inputs(face: adsk.fusion.BRepFace, cut: Vector3D,  inputs: PatternInputs) -> adsk.fusion.BRepBody:
    params = RhombusParameters(
        width=inputs.preferred_width.value,
        height=inputs.preferred_height.value,
        spacing=inputs.spacing.value,
        inset=inputs.inset.value,
        fillet=inputs.fillet.value,
        adaptive=inputs.adaptive.value,
    )
    return create_rhombuses(face, cut, params)

def create_rhombuses(face: adsk.fusion.BRepFace, cut: Vector3D,  params: RhombusParameters) -> adsk.fusion.BRepBody:
    mgr = adsk.fusion.TemporaryBRepManager.get()
    long_edge, short_edge = utils.brep.longest_and_adjecent_edge_of_face(face)
    face_length = long_edge.length
    face_width = short_edge.length
    vertical_space = face_width - 2 * params.inset
    horizontal_space = face_length - 2 * params.inset

    def pattern_spacing(ratio: float) -> tuple[float, float]:
        angle = 2 * math.atan(ratio)
        sx = 2 * params.spacing * math.sin(angle/2) / math.sin(angle)
        sy = sx / ratio
        return (sx, sy)

    def pattern_dimensions(ratio: float) -> tuple[float, float, float, float]:
        sx, sy = pattern_spacing(ratio)
        w = (horizontal_space - (columns - 1) * sx) / columns
        h = w / ratio
        return (w, h, sx, sy)

    width = params.width
    height = params.height
    initial_ratio = width / height
    sx, sy = pattern_spacing(initial_ratio)
    rows = max(1, math.floor((vertical_space + sy) / (height + sy)))
    columns = max(1, math.floor((horizontal_space + sx) / (width + sx)))

    if params.adaptive:
        def height_deviation(ratio):
            _, h, _, sy = pattern_dimensions(ratio)
            actual_height = h * rows + sy * (rows - 1)
            return vertical_space - actual_height

        ratio_lower = initial_ratio * 0.5
        ratio_upper = initial_ratio * 1.5
        optimized_ratio = utils.misc.binary_search(ratio_lower, ratio_upper, height_deviation, 0, 0.1)
        width, height, sx, sy = pattern_dimensions(optimized_ratio)

    rhombus = utils.brep.rhombus(width, height, cut.length, params.fillet)
    row = mgr.copy(rhombus)
    for idx in range(columns):
        x = idx * (width + sx)
        t = mgr.copy(rhombus)
        mgr.transform(t, utils.matrix.translation_matrix(Vector3D.create(x, 0, 0)))
        mgr.booleanOperation(row, t, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore

    result = mgr.copy(row)
    for idx in range(1, rows):
        y = idx * (height + sy)
        r = mgr.copy(row)
        mgr.transform(r, utils.matrix.translation_matrix(Vector3D.create(0, y, 0)))
        mgr.booleanOperation(result, r, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore

    intermediate_row = mgr.copy(rhombus)
    for idx in range(columns - 1):
        t = mgr.copy(rhombus)
        mgr.transform(t, utils.matrix.translation_matrix(Vector3D.create(idx * (width + sx), 0, 0)))
        mgr.booleanOperation(intermediate_row, t, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore
    mgr.transform(intermediate_row, utils.matrix.translation_matrix(Vector3D.create((width + sx)/2, 0, 0)))

    for idx in range(rows - 1):
        r = mgr.copy(intermediate_row)
        mgr.transform(r, utils.matrix.translation_matrix(Vector3D.create(0, (height + sy)/2 + idx * (height + sy)))) 
        mgr.booleanOperation(result, r, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore

    if columns > 1:
        triangle_height = (height - sy) / 2
        triangle_angle = 2 * math.atan(width/height)
        triangle_width = math.tan(triangle_angle/2) * 2 * triangle_height
        triangle = utils.brep.isosceles_triangle(triangle_width, triangle_height, cut.length, params.fillet)
        triangle_row = mgr.copy(triangle)
        for idx in range(columns - 1):
            t = mgr.copy(triangle)
            mgr.transform(t, utils.matrix.translation_matrix(Vector3D.create(idx * (width + sx), 0, 0)))
            mgr.booleanOperation(triangle_row, t, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore
        mgr.transform(triangle_row, utils.matrix.translation_matrix(Vector3D.create((width + sx)/2, -height/2, -cut.length/2)))
        mgr.booleanOperation(result, triangle_row, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore
        mgr.transform(triangle_row, utils.matrix.mirror_matrix(Point3D.create(0, (rows - 1) * (height + sy)/2, 0), Vector3D.create(1, -1, 1)))
        mgr.booleanOperation(result, triangle_row, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore

    if rows > 1:
        triangle_height = (width - sx) / 2
        triangle_angle = 2 * math.atan(height/width)
        triangle_width = math.tan(triangle_angle/2) * 2 * triangle_height
        triangle = utils.brep.isosceles_triangle(triangle_width, triangle_height, cut.length, params.fillet)
        mgr.transform(triangle, utils.matrix.rotation_matrix(-math.pi/2, Vector3D.create(0, 0, 1), Point3D.create()))
        triangle_row = mgr.copy(triangle)
        for idx in range(rows - 1):
            t = mgr.copy(triangle)
            mgr.transform(t, utils.matrix.translation_matrix(Vector3D.create(0, idx * (height + sy), 0)))
            mgr.booleanOperation(triangle_row, t, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore
        mgr.transform(triangle_row, utils.matrix.translation_matrix(Vector3D.create(-width/2, (height + sy)/2, -cut.length/2)))
        mgr.booleanOperation(result, triangle_row, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore
        mgr.transform(triangle_row, utils.matrix.mirror_matrix(Point3D.create((columns - 1) * (width + sx)/2, 0, 0), Vector3D.create(-1, 1, 1)))
        mgr.booleanOperation(result, triangle_row, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore

    result_bb = result.preciseBoundingBox
    offset_x = face_length/2 - (result_bb.maxPoint.x + result_bb.minPoint.x)/2
    offset_y = face_width/2 - (result_bb.maxPoint.y + result_bb.minPoint.y)/2
    offset_z = -result_bb.minPoint.z
    mgr.transform(result, utils.matrix.translation_matrix(Vector3D.create(offset_x, offset_y, offset_z)))
    return result


def create_cross(face: adsk.fusion.BRepFace, cut: Vector3D,  inputs: PatternInputs) -> adsk.fusion.BRepBody:
    mgr = adsk.fusion.TemporaryBRepManager.get()
    long_edge, short_edge = utils.brep.longest_and_adjecent_edge_of_face(face)
    face_length = long_edge.length
    face_width = short_edge.length
    height = face_width - 2 * inputs.inset.value
    width = face_length - 2 * inputs.inset.value
    spacing = inputs.spacing.value

    alpha = math.atan(height/width)
    long_dx = (spacing/2) / math.sin(alpha)
    long_dy  = (spacing/2) / math.cos(alpha)
    beta = math.pi/2 - alpha
    short_dx = (spacing/2) / math.sin(beta)
    short_dy = (spacing/2) / math.cos(beta)

    long_triangle = utils.brep.isosceles_triangle(width - 2*long_dx, height/2 - long_dy, cut.length, inputs.fillet.value)
    mgr.transform(long_triangle, utils.matrix.translation_matrix(Vector3D.create(0, -height/2, 0)))
    short_triangle = utils.brep.isosceles_triangle(height - 2*short_dx, width/2 - short_dy, cut.length, inputs.fillet.value)
    mgr.transform(short_triangle, utils.matrix.combine_transforms([
        utils.matrix.translation_matrix(Vector3D.create(0, -width/2, 0)),
        utils.matrix.rotation_matrix(-math.pi/2, Vector3D.create(0, 0, 1), Point3D.create()),
    ]))
    result = mgr.copy(long_triangle)
    mgr.transform(long_triangle, utils.matrix.mirror_matrix(Point3D.create(), Vector3D.create(1, -1, 1)))
    mgr.booleanOperation(result, long_triangle, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore
    mgr.booleanOperation(result, short_triangle, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore
    mgr.transform(short_triangle, utils.matrix.mirror_matrix(Point3D.create(), Vector3D.create(-1, 1, 1)))
    mgr.booleanOperation(result, short_triangle, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore

    result_bb = result.preciseBoundingBox
    offset_x = face_length/2 - (result_bb.maxPoint.x + result_bb.minPoint.x)/2
    offset_y = face_width/2 - (result_bb.maxPoint.y + result_bb.minPoint.y)/2
    mgr.transform(result, utils.matrix.translation_matrix(Vector3D.create(offset_x, offset_y, 0)))
    return result
    

def create_rounded_rect(face: adsk.fusion.BRepFace, cut: Vector3D,  inputs: PatternInputs) -> adsk.fusion.BRepBody:
    long_edge, short_edge = utils.brep.longest_and_adjecent_edge_of_face(face)
    face_length = long_edge.length
    face_width = short_edge.length
    height = face_width - 2 * inputs.inset.value
    width = face_length - 2 * inputs.inset.value

    result = utils.brep.rounded_rectangle(width, height, cut.length, inputs.fillet.value)
    result_bb = result.preciseBoundingBox
    offset_x = face_length/2 - (result_bb.maxPoint.x + result_bb.minPoint.x)/2
    offset_y = face_width/2 - (result_bb.maxPoint.y + result_bb.minPoint.y)/2
    return utils.brep.transformed(result, utils.matrix.translation_matrix(Vector3D.create(offset_x, offset_y, 0)))


def create_froli_grid(face: adsk.fusion.BRepFace, cut: Vector3D,  inputs: PatternInputs) -> adsk.fusion.BRepBody:
    long_edge, short_edge = utils.brep.longest_and_adjecent_edge_of_face(face)
    face_length = long_edge.length
    face_width = short_edge.length
    vertical_space = face_width - 1 # Give at least 5mm spacing on each side
    horizontal_space = face_length - 1

    def spacing(length: float) -> float:
        available = length - 13.6 # Subtract width of one froli element
        remainders = [((available/x % 1) * x, x) for x in [16.3, 17.5, 18.7]]
        remainders.sort(key=lambda x: x[0])
        return remainders[0][1]

    horizontal_grid = spacing(horizontal_space)
    vertical_grid = spacing(vertical_space)

    tan_alpha = horizontal_grid/vertical_grid
    alpha = math.atan(tan_alpha)
    x_inset = inputs.spacing.value / (2 * math.cos(alpha))
    y_inset = x_inset / tan_alpha
    width = horizontal_grid - 2 * x_inset
    height = vertical_grid - 2 * y_inset

    return create_rhombuses(face, cut, RhombusParameters(
        width=width,
        height=height,
        spacing=inputs.spacing.value,
        inset=inputs.inset.value,
        fillet=inputs.fillet.value,
        adaptive=False
    ))

def create_adaptive(face: adsk.fusion.BRepFace, cut: Vector3D, coords: tuple[Point3D, Vector3D, Vector3D, Vector3D], inputs: PatternInputs) -> adsk.fusion.BRepBody:
    long_edge, short_edge = utils.brep.longest_and_adjecent_edge_of_face(face)
    origin, xn, yn, _ = coords
    origin = origin.asVector()

    # Create base box
    face_length = long_edge.length
    face_width = short_edge.length
    inset = inputs.inset.value
    height = face_width - 2*inset
    width = face_length - 2*inset
    cut_body = utils.brep.transformed(utils.brep.rectangle(width, height, cut.length), utils.matrix.translation_matrix(Vector3D.create(face_length/2, face_width/2, 0)))

    # Create cutouts for inner loops
    offset = inputs.inner_loop_offset.value
    measure = adsk.core.Application.get().measureManager
    inner_loops = [l for l in face.loops if not l.isOuter]
    bbs: list[adsk.core.OrientedBoundingBox3D] = []
    for l in inner_loops:
        loop_bb = measure.getOrientedBoundingBox(l, xn, yn)
        loop_bb.length += 2*offset
        loop_bb.width += 2*offset
        center = utils.vector.subtract(loop_bb.centerPoint.asVector(), origin)
        loop_bb.centerPoint = Point3D.create(center.dotProduct(xn), center.dotProduct(yn), 0)
        bbs.append(loop_bb)

    # Expand cutouts to edges if there's no material remaining
    if inputs.remainder.value == 0:
        for bb in bbs:
            xl = bb.centerPoint.x - bb.length/2 - inset
            xr = (face_length - inset) - (bb.centerPoint.x + bb.length/2)
            yb = bb.centerPoint.y - bb.width/2 - inset
            yt = (face_width - inset) - (bb.centerPoint.y + bb.width/2)
            distances = [
                (xl, Vector3D.create(-xl/2, 0, 0)),
                (xr, Vector3D.create(xr/2, 0, 0)),
                (yb, Vector3D.create(0, -yb/2, 0)),
                (yt, Vector3D.create(0, yt/2, 0))
            ]
            distances.sort(key=lambda x: x[0])
            for idx, d in enumerate(distances):
                if d[0] > 0 and (idx == 0 or d[0] < inputs.fillet.value*2):
                    bb.length += abs(d[1].x)*2
                    bb.width += abs(d[1].y)*2
                    bb.centerPoint = utils.vector.add(bb.centerPoint.asVector(), d[1]).asPoint()
            
    for bb in bbs:
        loop_body = utils.brep.transformed(utils.brep.rectangle(bb.length, bb.width, cut.length), utils.matrix.translation_matrix(Vector3D.create(bb.centerPoint.x, bb.centerPoint.y, 0)))
        cut_body = utils.brep.subtract(cut_body, loop_body)

    # Apply fillets to outer corners of the cut body
    fillet = inputs.fillet.value
    if fillet > 0:
        faces = utils.fusion.as_list(cut_body.faces)
        faces.sort(key=lambda f: f.area, reverse=True)
        box_face = next((f for f in faces if f.centroid.z == 0))
        box_edges = utils.brep.outer_edges_of_face(box_face)
        for edge1, edge2 in zip(box_edges, box_edges[1:] + [box_edges[0]]):
            point = edge1.endVertex.geometry.asVector()
            leg1 = utils.vector.subtract(edge1.startVertex.geometry.asVector(), point)
            leg2 = utils.vector.subtract(edge2.endVertex.geometry.asVector(), point)
            fillet_cut_body = utils.brep.fillet_cut_body(point.asPoint(), leg1, leg2, inputs.fillet.value, Vector3D.create(0, 0, cut.length))
            corner_test = utils.vector.add(
                point,
                utils.vector.scaled_by(utils.vector.normalized(utils.vector.add(leg1, leg2)), 0.1)
            ).asPoint()
            _, test_param = box_face.evaluator.getParameterAtPoint(corner_test)
            is_inner_corner = box_face.evaluator.isParameterOnFace(test_param)
            if is_inner_corner:
                cut_body = utils.brep.subtract(cut_body, fillet_cut_body)
            else:            
                cut_body = utils.brep.union([cut_body, fillet_cut_body])

    return cut_body
