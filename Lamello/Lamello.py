import sys, os
import math

import adsk.core, adsk.fusion
from adsk.core import Point3D, Vector3D

# -------------------------------------------------------------------------
# Path handling so SharedUtils can be imported
# -------------------------------------------------------------------------
current_dir = os.path.dirname(__file__)
parent_dir = os.path.dirname(current_dir)
shared_folder = os.path.join(parent_dir, "SharedUtils")

if current_dir not in sys.path:
    sys.path.append(current_dir)
if shared_folder not in sys.path:
    sys.path.append(shared_folder)

import CustomComputeFeature, Inputs, utils
utils.misc.force_reload_modules('CustomComputeFeature', 'Inputs', 'utils')

# -------------------------------------------------------------------------
# Globals for Fusion entry points
# -------------------------------------------------------------------------
_feature: CustomComputeFeature.CustomComputeFeature = None


def run(context):
    global _feature
    _feature = Lamello()


def stop(context):
    global _feature
    del _feature


# -------------------------------------------------------------------------
# Inputs
# -------------------------------------------------------------------------
class LamelloInputs(Inputs.Inputs):
    def __init__(self, units_manager: adsk.core.UnitsManager):
        units = units_manager.defaultLengthUnits

        self.edge = Inputs.SelectionByEntityTokenInput(
            'edge',
            'Edge',
            'LinearEdges',
            1,
            0,
            'Select edge along which access holes should be placed.'
        )

        self.points = Inputs.SelectionByEntityTokenInput(
            'points',
            'Points',
            'SketchPoints',
            0,
            0,
            'To manually place the connectors, select sketch points.'
        )

        # 12 = Cabineo 12, 10 = Clamex P10, 14 = Clamex P14,
        self.size = Inputs.DropDownInput(
        'size',
        'Variant',
        [
            ['Cabineo 12', 12],   # jetzt zuerst
            ['Clamex P10', 10],
            ['Clamex P14', 14],
        ],
        12,                      # Default-Wert: Cabineo 12
        'Variant of the Lamello / Cabineo connector.'
    )


        self.spacing = Inputs.FloatInput(
            'spacing',
            'Spacing',
            20,
            'Minimum spacing between the connectors.',
            units
        )

        self.offset = Inputs.FloatInput(
            'offset',
            'Offset',
            6,
            'Distance of the first connector from the start of the edge.',
            units
        )

        self.through_guide_holes = Inputs.CheckboxInput(
            'throughGuideHoles',
            'Through Guide Holes',
            False,
            'If checked the guide holes are punched all the way through to the opposite face.'
        )

        super().__init__()


# -------------------------------------------------------------------------
# Feature implementation
# -------------------------------------------------------------------------
class Lamello(CustomComputeFeature.CustomComputeFeature):
    plugin_id = 'antonLamello'
    plugin_name = 'Lamello'
    plugin_desc = 'Lamello / Cabineo connectors'
    plugin_tooltip = 'Adds access & guide holes for Lamello / Cabineo connectors along an edge.'
    inputs: LamelloInputs

    def create_inputs(self) -> LamelloInputs:
        return LamelloInputs(self.app.activeProduct.unitsManager)

    def execute(self) -> list[CustomComputeFeature.Combine]:
        combines: list[CustomComputeFeature.Combine] = []

        for edge in self.inputs.edge.value:
            faces = find_faces(edge)
            if not faces:
                continue

            access_face, slot_face, guide_face = faces

            access_holes, guide_holes = create_hole_bodies(
                edge,
                access_face,
                slot_face,
                guide_face,
                self.inputs
            )

            combines.append(
                CustomComputeFeature.Combine(
                    access_face.body,
                    access_holes,
                    adsk.fusion.FeatureOperations.CutFeatureOperation
                )
            )
            combines.append(
                CustomComputeFeature.Combine(
                    guide_face.body,
                    guide_holes,
                    adsk.fusion.FeatureOperations.CutFeatureOperation
                )
            )

        return combines

    def pre_select(self, input: adsk.core.SelectionCommandInput,
                   entity: adsk.fusion.BRepEdge) -> bool:
        if input.id == self.inputs.edge.id:
            return find_faces(entity) is not None
        else:
            return True

    def input_changed(self, _):
        spacing_enabled = self.inputs.points.input.selectionCount == 0
        self.inputs.spacing.input.isEnabled = spacing_enabled
        self.inputs.offset.input.isEnabled = spacing_enabled


# -------------------------------------------------------------------------
# Geometry helper functions
# -------------------------------------------------------------------------
def find_faces(edge: adsk.fusion.BRepEdge) -> tuple[
    adsk.fusion.BRepFace,
    adsk.fusion.BRepFace,
    adsk.fusion.BRepFace
] | None:
    access_face, slot_face = get_access_and_slot_faces(edge)
    if not access_face or not slot_face:
        return None

    guide_face = find_guide_face(edge, access_face, slot_face)
    if not guide_face:
        return None

    return access_face, slot_face, guide_face


def find_guide_face(edge: adsk.fusion.BRepEdge,
                    access_face: adsk.fusion.BRepFace,
                    slot_face: adsk.fusion.BRepFace) -> adsk.fusion.BRepFace | None:
    slot_normal = utils.brep.normal_into_face(edge, slot_face)
    slot_dir = utils.vector.scaled_by(slot_normal, 0.5)
    edge_normal = utils.brep.normal_along_edge(edge)
    step = utils.vector.scaled_by(edge_normal, 5)

    start = utils.vector.add(
        edge.startVertex.geometry.asVector(),
        slot_dir
    )

    test_points = []
    for x in range(0, math.floor(edge.length / 5)):
        test_points.append(
            utils.vector.add(start, utils.vector.scaled_by(step, x)).asPoint()
        )

    def check_face(face: adsk.fusion.BRepFace):
        for t in test_points:
            _, param = face.evaluator.getParameterAtPoint(t)
            if face.evaluator.isParameterOnFace(param):
                return True
        return False

    return utils.brep.find_perpendicular_face_containing_edge(
        edge,
        access_face,
        check_face
    )


def get_access_and_slot_faces(edge: adsk.fusion.BRepEdge) -> tuple[
    adsk.fusion.BRepFace | None,
    adsk.fusion.BRepFace | None
]:
    access_face = utils.brep.largest_face_of_edge(edge)
    slot_face = None

    for f in edge.faces:
        if f != access_face and utils.brep.is_planar(f):
            slot_face = f
            break

    return access_face, slot_face

def access_positions_by_spacing(edge: adsk.fusion.BRepEdge,
                                spacing: float,
                                offset: float) -> list[adsk.core.Vector3D]:
    total_length = edge.length
    edge_dir = utils.brep.normal_along_edge(edge)
    start_vec = edge.startVertex.geometry.asVector()

    # Schutzfälle
    if total_length <= 0:
        return []

    usable_length = total_length - 2 * offset  # Bereich zwischen den Offsets

    # Wenn das Brett kürzer als 2*Offset ist → ein Verbinder in der Mitte
    if usable_length <= 0:
        mid_vec = utils.vector.add(
            start_vec,
            utils.vector.scaled_by(edge_dir, total_length / 2)
        )
        return [mid_vec]

    # Spacing ist MAXIMALER Abstand auf der nutzbaren Länge
    if spacing <= 0:
        # Fallback: nur zwei Verbinder an den Offsets
        n_segments = 1
    else:
        n_segments = max(1, math.ceil(usable_length / spacing))

    # Tatsächlicher Abstand (≤ spacing)
    actual_spacing = usable_length / n_segments

    # Verbinder-Positionen:
    # Erster bei "offset" von Start,
    # letzter bei "total_length - offset",
    # dazwischen gleich verteilt.
    positions: list[adsk.core.Vector3D] = []
    for i in range(n_segments + 1):
        dist_along_edge = offset + i * actual_spacing
        pos_vec = utils.vector.add(
            start_vec,
            utils.vector.scaled_by(edge_dir, dist_along_edge)
        )
        positions.append(pos_vec)

    return positions


"""def access_positions_by_spacing(edge: adsk.fusion.BRepEdge,
                                spacing: float,
                                offset: float) -> list[adsk.core.Vector3D]:
    available_length = edge.length - 2 * offset
    number_of_holes = max(1, math.ceil(available_length / spacing))

    edge_normal = utils.brep.normal_along_edge(edge)

    if number_of_holes > 1:
        start_offset = offset
    else:
        # Einzelner Connector mittig auf der Kante
        start_offset = edge.length / 2

    start = utils.vector.add(
        edge.startVertex.geometry.asVector(),
        utils.vector.scaled_by(edge_normal, start_offset)
    )

    computed_spacing = available_length / (number_of_holes - 1) if number_of_holes > 1 else 0

    return [
        utils.vector.add(start, utils.vector.scaled_by(edge_normal, idx * computed_spacing))
        for idx in range(number_of_holes)
    ]"""


# -------------------------------------------------------------------------
# Hole body creation (Clamex P10, P14, Cabineo 12)
# -------------------------------------------------------------------------
def create_hole_bodies(edge: adsk.fusion.BRepEdge,
                       access_face: adsk.fusion.BRepFace,
                       slot_face: adsk.fusion.BRepFace,
                       guide_face: adsk.fusion.BRepFace,
                       inputs: LamelloInputs) -> tuple[
                           adsk.fusion.BRepBody,
                           adsk.fusion.BRepBody
                       ]:
    mgr = adsk.fusion.TemporaryBRepManager.get()
    thickness = utils.brep.get_board_thickness(access_face)

    # Positions along the selected edge
    if len(inputs.points.value) > 0:
        positions = [p.worldGeometry.asVector() for p in inputs.points.value]
    else:
        positions = access_positions_by_spacing(
            edge,
            inputs.spacing.value,
            inputs.offset.value
        )

    size = inputs.size.value

    # ------------------------------------------------------------------
    # Cabineo 12
    #   Access-Hole: 3 x Ø15 mm, Tiefe 11 mm (Option 1)
    #   Guide-Hole : Ø5 mm, Tiefe 12 mm,
    #                Mittelpunkt 5 mm von der Kantenoberfläche
    # ------------------------------------------------------------------
    if size == 12:
        # Access-Holes: 3 x Ø15 mm, Tiefe 11 mm
        access_depth = 1.1                # 11 mm
        access_radius = 1.5 / 2.0         # Ø15 mm
        center_spacing = 1.12             # 11.2 mm (in cm)
        edge_offset = 0.36                # 3.6 mm (in cm) Abstand von der Bezugslinie

        base_cyl = utils.brep.cylinder(access_radius, -access_depth)

        # Drei Zylinder nur in +Y-Richtung, nach Zeichnung:
        c1 = utils.brep.transformed(
            base_cyl,
            utils.matrix.translation_matrix(
                Vector3D.create(0, edge_offset, 0)        # 3,6 mm
            )
        )
        c2 = utils.brep.transformed(
            base_cyl,
            utils.matrix.translation_matrix(
                Vector3D.create(0, edge_offset + center_spacing, 0)  # 14,8 mm
            )
        )
        c3 = utils.brep.transformed(
            base_cyl,
            utils.matrix.translation_matrix(
                Vector3D.create(0, edge_offset + 2 * center_spacing, 0)  # 26,0 mm
            )
        )

        access_hole = utils.brep.union([c1, c2, c3])

        # Guide-Hole (Schraubenloch) bleibt wie gehabt:
        guide_hole_radius = 0.50 / 2.0  # Ø 5 mm

        if inputs.through_guide_holes.value:
            # Komplett durch die Platte bohren
            guide_hole_depth = utils.brep.get_board_thickness(guide_face)
        else:
            # Standard 12 mm Tiefloch
            guide_hole_depth = 1.20

        guide_hole = utils.brep.cylinder(guide_hole_radius, guide_hole_depth)

        # Mittelpunkt 5 mm von der Oberfläche
        guide_hole_edge_distance = 0.5
        mgr.transform(
            guide_hole,
            utils.matrix.translation_matrix(
                Vector3D.create(0, guide_hole_edge_distance, 0)
            )
        )


        guide_holes = guide_hole

    # ------------------------------------------------------------------
    # Clamex P14
    # ------------------------------------------------------------------
    else:
        access_depth = thickness / 2
        access_hole_radius = 0.6 / 2
        access_edge_distance = 0.75

        if size == 14:
            cyl = utils.brep.cylinder(access_hole_radius, -access_depth)
            access_hole = utils.brep.transformed(
                cyl,
                utils.matrix.translation_matrix(
                    Vector3D.create(0, access_edge_distance, 0)
                )
            )
        # ------------------------------------------------------------------
        # Clamex P10
        # ------------------------------------------------------------------
        else:
            access_hole = utils.brep.slot(0.25, access_hole_radius, access_depth)
            mgr.transform(
                access_hole,
                utils.matrix.combine_transforms([
                    utils.matrix.rotation_matrix(
                        -math.pi / 2,
                        Vector3D.create(0, 0, 1),
                        Point3D.create(0, 0, 0)
                    ),
                    utils.matrix.translation_matrix(
                        Vector3D.create(0, access_edge_distance, -access_depth)
                    )
                ])
            )

        # Guide-Holes für Clamex (wie im Original)
        guide_hole_depth = (
            utils.brep.get_board_thickness(guide_face)
            if inputs.through_guide_holes.value else
            0.8
        )
        guide_hole_radius = 0.77 / 2
        guide_hole_distance = 10.1
        guide_hole_edge_distance = thickness / 2

        cyl = utils.brep.cylinder(guide_hole_radius, guide_hole_depth)
        guide_hole = utils.brep.transformed(
            cyl,
            utils.matrix.translation_matrix(
                Vector3D.create(guide_hole_distance / 2, guide_hole_edge_distance, 0)
            )
        )
        guide_holes = utils.brep.union([
            guide_hole,
            utils.brep.transformed(
                guide_hole,
                utils.matrix.translation_matrix(
                    Vector3D.create(-guide_hole_distance, 0, 0)
                )
            )
        ])

    # Place the access and guide bodies on the corresponding faces
    access_bodies = utils.brep.place_body_on_face_at_positions(
        access_hole,
        access_face,
        edge,
        positions
    )

    guide_bodies = utils.brep.place_body_on_face_at_positions(
        guide_holes,
        slot_face,
        edge,
        positions
    )

    return access_bodies, guide_bodies
import sys, os
current_dir = os.path.dirname(__file__)
parent_dir = os.path.dirname(current_dir)
shared_folder = os.path.join(parent_dir, "SharedUtils")
if current_dir not in sys.path: sys.path.append(current_dir)
if shared_folder not in sys.path: sys.path.append(shared_folder)
import CustomComputeFeature, Inputs, Combine, utils
import adsk.core, adsk.fusion
from adsk.core import Point3D, Vector3D
import math
from typing import cast, Optional
utils.misc.force_reload_modules('CustomComputeFeature', 'Inputs', 'Combine', 'utils')

_feature: CustomComputeFeature.CustomComputeFeature

def run(context):
    global _feature
    _feature = Lamello()

def stop(context):
    global _feature
    del _feature

class LamelloInputs(Inputs.Inputs):
    class Types:
        CLAMEX_P10 = Inputs.DropDownInput.Item('Clamex P10', 10)
        CLAMEX_P14 = Inputs.DropDownInput.Item('Clamex P14', 14)

    def __init__(self, units_manager: adsk.core.UnitsManager):
        units = units_manager.defaultLengthUnits
        self.edge = Inputs.SelectionByEntityTokenInput('edge', 'Edge', 'LinearEdges', 1, 0, 'Select edge along which access holes should be placed.')
        self.points = Inputs.SelectionByEntityTokenInput('points', 'Points', 'SketchPoints', 0, 0, 'To manually place the connectors, select sketch points.')
        self.size = Inputs.DropDownInput('size', 'Variant', utils.misc.class_property_values(LamelloInputs.Types), LamelloInputs.Types.CLAMEX_P10.value, 'Variant of the Lamello connector.')
        self.spacing = Inputs.FloatInput('spacing', 'Spacing', 20, 'Minimum spacing between the connectors.', units)
        self.offset = Inputs.FloatInput('offset', 'Offset', 6, 'Distance of the first connector from the start of the edge.', units)
        self.through_guide_holes = Inputs.CheckboxInput('throughGuideHoles', 'Through Guide Holes', False, 'If checked the guide holes are punched all the way through to the opposite face.')
        super().__init__()


class Lamello(CustomComputeFeature.CustomComputeFeature):
    plugin_id = 'antonLamello'
    plugin_name = 'Lamello'
    plugin_desc = 'Lamello connectors'
    plugin_tooltip = 'Adds access guide holes for Lamello connectors along an edge.'
    inputs: LamelloInputs

    def create_inputs(self) -> LamelloInputs:
        return LamelloInputs(self.app.activeProduct.unitsManager)

    def execute(self) -> list[Combine.Combine]:
        combines: list[Combine.Combine] = []
        for edge in cast(list[adsk.fusion.BRepEdge], self.inputs.edge.value):
            faces = find_faces(edge)
            if not faces:
                continue
            access_face, slot_face, guide_face = faces[0:3]
            access_holes, guide_holes = create_hole_bodies(edge, access_face, slot_face, guide_face, self.inputs)
            combines.append(Combine.Combine(access_face.body, access_holes, Combine.Operation.CUT))
            combines.append(Combine.Combine(guide_face.body, guide_holes, Combine.Operation.CUT))
        return combines
    
    def pre_select(self, input: adsk.core.SelectionCommandInput, selection: adsk.fusion.BRepEdge) -> bool:
        if input.id == self.inputs.edge.id:
            return find_faces(selection) is not None
        else:
            return True
        
    def input_changed(self, input):
        spacing_enabled = self.inputs.points.input.selectionCount == 0
        self.inputs.spacing.input.isEnabled = spacing_enabled
        self.inputs.offset.input.isEnabled = spacing_enabled

def find_faces(edge: adsk.fusion.BRepEdge) -> Optional[tuple[adsk.fusion.BRepFace, adsk.fusion.BRepFace, adsk.fusion.BRepFace]]:
    access_and_slot = get_access_and_slot_faces(edge)
    if not access_and_slot:
        return None
    access_face, slot_face = access_and_slot[0:2]
    guide_face = find_guide_face(edge, access_face, slot_face)
    if not guide_face:
        return None
    return access_face, slot_face, guide_face

def find_guide_face(edge: adsk.fusion.BRepEdge, access_face: adsk.fusion.BRepFace, slot_face: adsk.fusion.BRepFace) -> Optional[adsk.fusion.BRepFace]:
    slot_normal = utils.brep.normal_into_face(edge, slot_face)
    slot_dir = utils.vector.scaled_by(slot_normal, 0.5)
    edge_normal = utils.brep.normal_along_edge(edge)
    step = utils.vector.scaled_by(edge_normal, 5)
    start = utils.vector.add(edge.startVertex.geometry.asVector(), slot_dir)
    test_points = []
    for x in range(0, math.floor(edge.length/5)):
        test_points.append(utils.vector.add(start, utils.vector.scaled_by(step, x)).asPoint())

    def check_face(face: adsk.fusion.BRepFace):
        for t in test_points:
            _, param = face.evaluator.getParameterAtPoint(t)
            if face.evaluator.isParameterOnFace(param):
                return True
        return False

    return utils.brep.find_perpendicular_face_containing_edge(edge, access_face, check_face)


def get_access_and_slot_faces(edge: adsk.fusion.BRepEdge) -> Optional[tuple[adsk.fusion.BRepFace, adsk.fusion.BRepFace]]:
    access_face = utils.brep.largest_face_of_edge(edge)
    if not access_face: return None
    for f in edge.faces:
        if f != access_face and utils.brep.is_planar(f):
            return access_face, f
    return None

def access_positions_by_spacing(edge: adsk.fusion.BRepEdge, spacing: float, offset: float) -> list[adsk.core.Vector3D]:
    available_length = edge.length - 2 * offset
    number_of_holes = max(1, math.ceil(available_length/spacing))
    edge_normal = utils.brep.normal_along_edge(edge)
    start = utils.vector.add(edge.startVertex.geometry.asVector(), utils.vector.scaled_by(edge_normal, offset if number_of_holes > 1 else edge.length/2))
    computed_spacing = available_length / (number_of_holes-1) if number_of_holes > 1 else 0
    return [utils.vector.add(start, utils.vector.scaled_by(edge_normal, idx * computed_spacing)) for idx in range(number_of_holes)]

def create_hole_bodies(edge: adsk.fusion.BRepEdge, access_face: adsk.fusion.BRepFace, slot_face: adsk.fusion.BRepFace, guide_face: adsk.fusion.BRepFace, inputs: LamelloInputs) -> tuple[adsk.fusion.BRepBody, adsk.fusion.BRepBody]:
    mgr = adsk.fusion.TemporaryBRepManager.get()
    thickness = utils.brep.get_board_thickness(access_face)
    positions: list[adsk.core.Vector3D]
    if len(inputs.points.value) > 0:
        positions = [cast(adsk.fusion.SketchPoint, p).worldGeometry.asVector() for p in inputs.points.value]
    else:
        positions = access_positions_by_spacing(edge, inputs.spacing.value, inputs.offset.value)

    access_hole = None
    access_depth = thickness/2
    access_hole_radius = 0.6/2
    access_edge_distance = 0.75
    if inputs.size.value == LamelloInputs.Types.CLAMEX_P14.value:
        cyl = utils.brep.cylinder(access_hole_radius, -access_depth)
        access_hole = utils.brep.transformed(cyl, utils.matrix.translation_matrix(Vector3D.create(0, access_edge_distance, 0)))
    elif inputs.size.value == LamelloInputs.Types.CLAMEX_P10.value:
        access_hole = utils.brep.slot(0.25, access_hole_radius, access_depth)
        mgr.transform(access_hole, utils.matrix.combine_transforms([
            utils.matrix.rotation_matrix(-math.pi/2, Vector3D.create(0, 0, 1), Point3D.create(0, 0, 0)),
            utils.matrix.translation_matrix(Vector3D.create(0, access_edge_distance, -access_depth))
        ]))
    else:
        raise ValueError(f"Invalid Lamello Type: {inputs.size.value}")

    guide_hole_depth = utils.brep.get_board_thickness(guide_face) if inputs.through_guide_holes.value else 0.8
    guide_hole_radius = 0.77/2
    guide_hole_distance = 10.1
    guide_hole_edge_distance = thickness/2
    cyl = utils.brep.cylinder(guide_hole_radius, guide_hole_depth)
    guide_hole = utils.brep.transformed(cyl, utils.matrix.translation_matrix(Vector3D.create(guide_hole_distance/2, guide_hole_edge_distance, 0)))
    guide_holes = utils.brep.union([
        guide_hole,
        utils.brep.transformed(guide_hole, utils.matrix.translation_matrix(Vector3D.create(-guide_hole_distance, 0, 0)))
    ])

    access_bodies = utils.brep.place_body_on_face_at_positions(access_hole, access_face, edge, positions)
    guide_bodies = utils.brep.place_body_on_face_at_positions(guide_holes, slot_face, edge, positions)
    return access_bodies, guide_bodies
