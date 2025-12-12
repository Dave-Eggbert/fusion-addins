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
from enum import Enum
utils.misc.force_reload_modules('CustomComputeFeature', 'Inputs', 'utils', 'Combine')

_feature: CustomComputeFeature.CustomComputeFeature

def run(context):
    global _feature
    _feature = DoorLatch()

def stop(context):
    global _feature
    del _feature

class DoorLadgeInputs(Inputs.Inputs):
    class Types:
        EVERLOCK = Inputs.DropDownInput.Item('Everlock', 0)
        PULL_LOCK_44 = Inputs.DropDownInput.Item('Pull Lock 44mm', 1)

    def __init__(self, units_manager: adsk.core.UnitsManager):
        units = units_manager.defaultLengthUnits
        self.door_edges = Inputs.SelectionByEntityTokenInput('edges', 'Door latch edges', 'LinearEdges', 1, 0, 'Select the (inner) edges of the doors at which the latch should be placed.')
        self.type = Inputs.DropDownInput('type', 'Latch type', utils.misc.class_property_values(DoorLadgeInputs.Types), DoorLadgeInputs.Types.EVERLOCK.value, 'The type of latch to use.')
        self.number = Inputs.IntegerInput('number', 'Number of latches', 1, 1, 10, 'The number of latches to place in the door')
        self.offset = Inputs.FloatInput('offset', 'Offset', 10, 'Offset of the first and last latch from the door\'s edge', units)
        self.predrill_diameter = Inputs.FloatInput('predrillDiameter', 'Predrill Diameter', 2.54/8, 'Predrill diameter used for screw holes.', units) 
        self.predrill_depth = Inputs.FloatInput('predrillDepth', 'Predrill Depth', 0.3, 'Predrill depth used for screw holes.', units) 
        super().__init__()


class DoorLatch(CustomComputeFeature.CustomComputeFeature):
    plugin_id = 'antonDoorLatch'
    plugin_name = 'Door Latch'
    plugin_desc = 'Creates the geometry for different kinds of door latches'
    plugin_tooltip = 'Creates the geometry for different kinds of door latches'
    inputs: DoorLadgeInputs

    def create_inputs(self) -> DoorLadgeInputs:
        return DoorLadgeInputs(self.app.activeProduct.unitsManager)

    def execute(self) -> list[Combine.Combine]:
        result: list[Combine.Combine] = []
        for door_edge in cast(list[adsk.fusion.BRepEdge], self.inputs.door_edges.value):
            door_face = utils.brep.largest_face_of_edge(door_edge)
            assert(door_face is not None)
            carcass_edge = utils.brep.find_carcass_edge_for_front_edge(door_edge, door_face)
            if not carcass_edge:
                continue
            positions = self.latch_positions(door_edge)
            carcass_geometry = self.carcass_holes(carcass_edge, positions)
            door_geometry = self.door_holes(carcass_edge, door_edge, door_face, positions)
            result.append(Combine.Combine(carcass_edge.body, carcass_geometry, Combine.Operation.CUT))
            result.append(Combine.Combine(door_face.body, door_geometry, Combine.Operation.CUT))
        return result
    
    def input_changed(self, input):
        if input == self.inputs.number.input:
            self.inputs.offset.input.isVisible = self.inputs.number.value > 1
    
    def latch_positions(self, door_edge: adsk.fusion.BRepEdge) -> list[Vector3D]:
        start_point = door_edge.startVertex.geometry
        available = door_edge.length - 2*self.inputs.offset.value
        number_of_latches = self.inputs.number.value
        spacing = available / (number_of_latches - 1) if number_of_latches > 1 else 0
        start = door_edge.length/2 if number_of_latches == 1 else self.inputs.offset.value
        dir = utils.vector.subtract(door_edge.endVertex.geometry.asVector(), start_point.asVector())
        offsets = [start + spacing * x for x in range(number_of_latches)]
        return utils.vector.compute_points_along_vector(start_point, dir, offsets) 

    def carcass_holes(self, carcass_edge: adsk.fusion.BRepEdge, positions: list[Vector3D]) -> adsk.fusion.BRepBody:
        carcass_face = utils.brep.largest_face_of_edge(carcass_edge)
        assert(carcass_face is not None)
        normal_into_carcass_face = utils.brep.normal_into_face(carcass_edge, carcass_face)
        gap_vector = utils.vector.subtract(carcass_edge.startVertex.geometry.asVector(), positions[0])
        gap = normal_into_carcass_face.dotProduct(gap_vector)

        cyl = utils.brep.cylinder(self.inputs.predrill_diameter.value/2, -self.inputs.predrill_depth.value)
        body: adsk.fusion.BRepBody

        if self.inputs.type.value == DoorLadgeInputs.Types.EVERLOCK.value:
            hole = utils.brep.transformed(cyl, utils.matrix.translation_matrix(Vector3D.create(0, 2.5 - gap, 0)))
            body = utils.brep.union([
                utils.brep.transformed(hole, utils.matrix.translation_matrix(Vector3D.create(-2.8/2, 0, 0))),
                utils.brep.transformed(hole, utils.matrix.translation_matrix(Vector3D.create(2.8/2, 0, 0)))
            ])

        elif self.inputs.type.value == DoorLadgeInputs.Types.PULL_LOCK_44.value:

            hole = utils.brep.transformed(cyl, utils.matrix.translation_matrix(Vector3D.create(0, 2.9 - gap, 0)))
            body = utils.brep.union([
                utils.brep.transformed(hole, utils.matrix.translation_matrix(Vector3D.create(-1.9/2, 0, 0))),
                utils.brep.transformed(hole, utils.matrix.translation_matrix(Vector3D.create(1.9/2, 0, 0)))
            ])

        return utils.brep.place_body_on_face_at_positions(body, carcass_face, carcass_edge, positions)

    def door_holes(self, carcass_edge: adsk.fusion.BRepEdge, door_edge: adsk.fusion.BRepEdge, door_face: adsk.fusion.BRepFace, positions: list[Vector3D]) -> adsk.fusion.BRepBody:
        normal_into_door_face = utils.brep.normal_into_face(door_edge, door_face)
        distance_vector = utils.vector.subtract(door_edge.startVertex.geometry.asVector(), carcass_edge.startVertex.geometry.asVector())
        distance = - normal_into_door_face.dotProduct(distance_vector) 
        thickness = utils.brep.get_board_thickness(door_face)

        body: adsk.fusion.BRepBody

        if self.inputs.type.value == DoorLadgeInputs.Types.EVERLOCK.value:
            screw_cyl = utils.brep.cylinder(self.inputs.predrill_diameter.value/2, -self.inputs.predrill_depth.value)
            screw_holes = utils.brep.union([
                utils.brep.transformed(screw_cyl, utils.matrix.translation_matrix(Vector3D.create(-2.6, distance + 2.6, 0))),
                utils.brep.transformed(screw_cyl, utils.matrix.translation_matrix(Vector3D.create(2.6, distance + 2.6, 0))),
            ])
            screw_holes = utils.brep.union([
                screw_holes,
                utils.brep.transformed(screw_holes, utils.matrix.translation_matrix(Vector3D.create(0, 1.6, 0)))
            ])

            finger_hole = utils.brep.transformed(utils.brep.cylinder(2.5/2, -thickness), utils.matrix.translation_matrix(Vector3D.create(0, 3 + distance, 0)))

            body = utils.brep.union([screw_holes, finger_hole])

        elif self.inputs.type.value == DoorLadgeInputs.Types.PULL_LOCK_44.value:

            lock_hole = utils.brep.cylinder(3.81/2, -thickness)
            if thickness > 1:
                lock_hole = utils.brep.union([
                    lock_hole,
                    utils.brep.cylinder(4.8/2, -(thickness-1))
                ])

            body = utils.brep.transformed(lock_hole, utils.matrix.translation_matrix(Vector3D.create(0, 3.4 + distance, 0)))

        return utils.brep.place_body_on_face_at_positions(body, door_face, door_edge, positions)
    
