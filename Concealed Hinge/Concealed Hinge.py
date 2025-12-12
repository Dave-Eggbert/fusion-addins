import sys, os
current_dir = os.path.dirname(__file__)
parent_dir = os.path.dirname(current_dir)
shared_folder = os.path.join(parent_dir, "SharedUtils")
if current_dir not in sys.path: sys.path.append(current_dir)
if shared_folder not in sys.path: sys.path.append(shared_folder)
import CustomComputeFeature, Inputs, utils, Combine
import adsk.core, adsk.fusion
from adsk.core import Point3D, Vector3D
from typing import cast
utils.misc.force_reload_modules('CustomComputeFeature', 'Inputs', 'utils', 'Combine')

_feature: CustomComputeFeature.CustomComputeFeature

def run(context):
    global _feature
    _feature = ConcealedHingeFeature()

def stop(context):
    global _feature
    del _feature

class ConcealedHingeInputs(Inputs.Inputs):
    class Types:
        BLUM_CLIP_TOP_THIN_0 = Inputs.DropDownInput.Item('Blum CLIP top 110 Thin +0', 0)
        BLUM_CLIP_TOP_THIN_3 = Inputs.DropDownInput.Item('Blum CLIP top 110 Thin +3', 1)

    def __init__(self, units_manager: adsk.core.UnitsManager):
        units = units_manager.defaultLengthUnits
        self.door_edges = Inputs.SelectionByEntityTokenInput('edges', 'Door hinge edges', 'LinearEdges', 1, 0, 'Select the hinged edge of the doors.')
        self.type = Inputs.DropDownInput('type', 'Hinge type', utils.misc.class_property_values(ConcealedHingeInputs.Types), ConcealedHingeInputs.Types.BLUM_CLIP_TOP_THIN_0.value, 'The type of pattern to use.')
        self.offset = Inputs.FloatInput('offset', 'Offset', 6, 'Distance of the first connector from the start of the edge.', units) 
        self.offset.minimum_value = 2.7
        self.predrill_diameter = Inputs.FloatInput('predrillDiameter', 'Predrill Diameter', 2.54/8, 'Predrill diameter used for screw holes.', units) 
        self.predrill_depth = Inputs.FloatInput('predrillDepth', 'Predrill Depth', 0.3, 'Predrill depth used for screw holes.', units) 
        super().__init__()


class ConcealedHingeFeature(CustomComputeFeature.CustomComputeFeature):
    plugin_id = 'antonConcealedHinge'
    plugin_name = 'Concealed Hinge'
    plugin_desc = 'Holes for concealed hinges'
    plugin_tooltip = 'Positions holes for concealed hinges'
    inputs: ConcealedHingeInputs

    def create_inputs(self) -> ConcealedHingeInputs:
        return ConcealedHingeInputs(self.app.activeProduct.unitsManager)

    def execute(self) -> list[Combine.Combine]:
        result: list[Combine.Combine] = []
        for door_edge in cast(list[adsk.fusion.BRepEdge], self.inputs.door_edges.value):
            door_face = utils.brep.largest_face_of_edge(door_edge)
            assert(door_face is not None)
            carcass_edge = utils.brep.find_carcass_edge_for_front_edge(door_edge, door_face)
            if not carcass_edge:
                continue
            positions = self.hinge_positions(carcass_edge, door_edge)
            carcass_geometry = self.carcass_holes(carcass_edge, door_face, positions)
            door_geometry = self.door_holes(carcass_edge, door_edge, door_face, positions)
            result.append(Combine.Combine(carcass_edge.body, carcass_geometry, Combine.Operation.CUT))
            result.append(Combine.Combine(door_face.body, door_geometry, Combine.Operation.CUT))
        return result
    
    def hinge_positions(self, carcass_edge: adsk.fusion.BRepEdge, door_edge: adsk.fusion.BRepEdge) -> list[Vector3D]:
        start_point = utils.brep.project_point_onto_edge(door_edge.startVertex.geometry, carcass_edge)
        end_point = utils.brep.project_point_onto_edge(door_edge.endVertex.geometry, carcass_edge)
        dir = utils.vector.subtract(end_point.asVector(), start_point.asVector())
        offset = self.inputs.offset.value
        return utils.vector.compute_points_along_vector(start_point, dir, [offset, dir.length - offset])

    def carcass_holes(self, carcass_edge: adsk.fusion.BRepEdge, door_face: adsk.fusion.BRepFace, positions: list[Vector3D]) -> adsk.fusion.BRepBody:
        point_on_face = utils.brep.project_point_onto_face(positions[0].asPoint(), door_face)
        carcass_face = utils.brep.largest_face_of_edge(carcass_edge)
        assert(carcass_face is not None)
        normal_into_carcass_face = utils.brep.normal_into_face(carcass_edge, carcass_face)
        gap_vector = utils.vector.subtract(point_on_face.asVector(), positions[0])
        gap = - normal_into_carcass_face.dotProduct(gap_vector)

        cyl = utils.brep.cylinder(self.inputs.predrill_diameter.value/2, -self.inputs.predrill_depth.value)
        cyl = utils.brep.transformed(cyl, utils.matrix.translation_matrix(Vector3D.create(0, 3.7 - (gap - 0.15), 0)))
        group = utils.brep.union([
            utils.brep.transformed(cyl, utils.matrix.translation_matrix(Vector3D.create(-1.6, 0, 0))),
            utils.brep.transformed(cyl, utils.matrix.translation_matrix(Vector3D.create(1.6, 0, 0)))
        ])
        return utils.brep.place_body_on_face_at_positions(group, carcass_face, carcass_edge, positions)

    def door_holes(self, carcass_edge: adsk.fusion.BRepEdge, hinge_edge: adsk.fusion.BRepEdge, door_face: adsk.fusion.BRepFace, positions: list[Vector3D]) -> adsk.fusion.BRepBody:
        normal_into_door_face = utils.brep.normal_into_face(hinge_edge, door_face)
        distance_vector = utils.vector.subtract(hinge_edge.startVertex.geometry.asVector(), carcass_edge.startVertex.geometry.asVector())
        distance = - normal_into_door_face.dotProduct(distance_vector) 

        match self.inputs.type.value:
            case ConcealedHingeInputs.Types.BLUM_CLIP_TOP_THIN_0.value:
                distance += 2.7
            case ConcealedHingeInputs.Types.BLUM_CLIP_TOP_THIN_3.value:
                distance += 3
        cyl = utils.brep.cylinder(0.5, -0.5)
        group = utils.brep.union([
            utils.brep.transformed(cyl, utils.matrix.translation_matrix(Vector3D.create(-1.6, distance, 0))),
            utils.brep.transformed(cyl, utils.matrix.translation_matrix(Vector3D.create(1.6, distance, 0)))
        ])
        return utils.brep.place_body_on_face_at_positions(group, door_face, hinge_edge, positions)
    
