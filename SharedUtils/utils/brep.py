import math
from typing import Callable, Optional, cast
from . import fusion, misc, matrix, vector
import adsk.core, adsk.fusion
from adsk.core import OrientedBoundingBox3D, Point3D, Vector3D, Matrix3D
from functools import singledispatch

def normal_into_face(edge: adsk.fusion.BRepEdge, face: adsk.fusion.BRepFace) -> Vector3D:
    eval = face.evaluator
    _, face_normal = eval.getNormalAtParameter(eval.parametricRange().minPoint)
    edge_normal = normal_along_edge(edge)
    result = edge_normal.crossProduct(face_normal)
    edge_mid = vector.add(edge.startVertex.geometry.asVector(), vector.scaled_by(edge_normal, edge.length/2))
    test_point = vector.add(edge_mid, vector.scaled_by(result, 0.1)).asPoint()
    _, test_param = eval.getParameterAtPoint(test_point)
    if not eval.isParameterOnFace(test_param):
        result.scaleBy(-1)
    return result

def adjecent_edge(edge: adsk.fusion.BRepEdge, face: adsk.fusion.BRepFace) -> adsk.fusion.BRepEdge:
    loop = next(l for l in face.loops if l.isOuter)
    edge_idx = fusion.as_list(loop.edges).index(edge)
    return loop.edges[edge_idx + 1] if edge_idx < len(loop.edges) - 1 else loop.edges[0]

def distance_along_normal_between_faces(face1: adsk.fusion.BRepFace, face2: adsk.fusion.BRepFace) -> float:
    assert(is_parallel(face1, face2))
    assert(isinstance(face1.geometry, adsk.core.Plane) and isinstance(face2.geometry, adsk.core.Plane))
    dir = face1.geometry.origin.vectorTo(face2.geometry.origin)
    return face1.geometry.normal.dotProduct(dir)

def normal_towards_face(from_face: adsk.fusion.BRepFace, to_face: adsk.fusion.BRepFace) -> Vector3D:
    assert(isinstance(from_face.geometry, adsk.core.Plane) and isinstance(to_face.geometry, adsk.core.Plane))
    normal: Vector3D = from_face.geometry.normal.copy()
    dist = distance_along_normal_between_faces(from_face, to_face)
    normal.scaleBy(dist)
    normal.normalize()
    return normal

def is_planar(face: adsk.fusion.BRepFace) -> bool:
    return face.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType
 
def is_linear(edge: adsk.fusion.BRepEdge) -> bool:
    return edge.geometry.curveType == adsk.core.Curve3DTypes.Line3DCurveType

def is_perpendicular(face1: adsk.fusion.BRepFace, face2: adsk.fusion.BRepFace) -> bool:
    if not isinstance(face1.geometry, adsk.core.Plane) or not isinstance(face2.geometry, adsk.core.Plane):
        return False
    return face1.geometry.normal.isPerpendicularTo(face2.geometry.normal)

@singledispatch
def is_parallel(a, b) -> bool:
    raise TypeError(f"Unsupported type: {type(a)}")

@is_parallel.register
def _(a: adsk.fusion.BRepFace, b: adsk.fusion.BRepFace) -> bool:
    if not isinstance(a.geometry, adsk.core.Plane) or not isinstance(b.geometry, adsk.core.Plane):
        return False
    return a.geometry.normal.isParallelTo(b.geometry.normal)

@is_parallel.register
def _(a: adsk.fusion.BRepEdge, b: adsk.fusion.BRepEdge) -> bool:
    if not is_linear(a) or not is_linear(b):
        return False
    n1 = normal_along_edge(a)
    n2 = normal_along_edge(b)
    return n1.isParallelTo(n2)

def get_opposite_face(face: adsk.fusion.BRepFace) -> adsk.fusion.BRepFace:
    if not is_planar(face): 
        raise ValueError("Face must be planar.")

    faces = []
    for f in face.body.faces:
        if f != face and is_parallel(face, f):
            faces.append(f)
    faces.sort(key=lambda x: x.area)
    return faces[-1]

def get_board_thickness(face: adsk.fusion.BRepFace) -> float:
    if not is_planar(face): 
        raise ValueError("Face must be planar.")

    opposite_face = get_opposite_face(face)
    if opposite_face is None:
        raise RuntimeError("No opposite planar face found.")

    return abs(distance_along_normal_between_faces(face, opposite_face))

def largest_face_of_edge(edge: adsk.fusion.BRepEdge) -> adsk.fusion.BRepFace | None:
    first_idx = next((idx for idx, face in enumerate(edge.faces) if is_planar(face)))
    if first_idx is None:
        return None
    face: adsk.fusion.BRepFace = edge.faces.item(first_idx)
    for idx in range(first_idx + 1, edge.faces.count):
        new_face = edge.faces.item(idx)
        if is_planar(new_face) and new_face.area > face.area:
            face = new_face
    return face

def face_contains_edge(face: adsk.fusion.BRepFace, edge: adsk.fusion.BRepEdge) -> bool:
    if not is_planar(face):
        return False

    return face.boundingBox.contains(edge.startVertex.geometry) and face.boundingBox.contains(edge.endVertex.geometry)

def find_perpendicular_face(reference_face: adsk.fusion.BRepFace, condition: Callable[[adsk.fusion.BRepFace], bool] = lambda _: True) -> Optional[adsk.fusion.BRepFace]:
    if not is_planar(reference_face):
        raise ValueError("Only works with planar reference face")
    
    result = None

    def search(o: adsk.fusion.Occurrence | adsk.fusion.Component) -> bool:
        for body in o.bRepBodies:
            if body == reference_face.body:
                continue
            for face in body.faces:
                if is_perpendicular(face, reference_face) and condition(face):
                    nonlocal result
                    result = face
                    return True
        return False

    fusion.traverse_occurrence_tree(reference_face.body.assemblyContext, search)
    return result

def find_perpendicular_face_containing_edge(edge: adsk.fusion.BRepEdge, reference_face: adsk.fusion.BRepFace, condition: Callable[[adsk.fusion.BRepFace], bool] = lambda _: True) -> adsk.fusion.BRepFace | None:
    if not is_linear(edge):
        raise ValueError("Only works on linear edges")
    return find_perpendicular_face(reference_face, lambda f: face_contains_edge(f, edge) and condition(f))

def find_carcass_edge_for_front_edge(front_edge: adsk.fusion.BRepEdge, front_face: adsk.fusion.BRepFace) -> adsk.fusion.BRepEdge | None:
    normal_into_door_face = normal_into_face(front_edge, front_face)
    _, door_edge_center = front_edge.geometry.evaluator.getPointAtParameter(0.5)

    carcass_edge: adsk.fusion.BRepEdge | None = None
    def check_face(face: adsk.fusion.BRepFace) -> bool:
        nonlocal carcass_edge
        
        # Check whether the face has the right orientation
        normal_into_carcass_body = normal_towards_face(face, get_opposite_face(face))
        if not vector.is_opposite_direction(normal_into_door_face, normal_into_carcass_body):
            return False
        
        # Check whether the center point of the door edge is within the bounds of the carcass edge
        edge = closest_parallel_edge_of_face(front_edge, face)
        if not edge:
            return False
        _, lower, upper = edge.geometry.evaluator.getParameterExtents()
        _, param = edge.geometry.evaluator.getParameterAtPoint(door_edge_center)
        if param <= lower or param >= upper:
            return False

        # Check whether the carcass edge lies within a reasonable distance from the door edge
        normal_into_carcass_face = normal_into_face(edge, face)
        delta = vector.subtract(front_edge.startVertex.geometry.asVector(), edge.startVertex.geometry.asVector())
        distance_along_door = normal_into_door_face.dotProduct(delta)
        distance_along_carcass = normal_into_carcass_face.dotProduct(delta)
        carcass_thickness = get_board_thickness(face)
        if distance_along_carcass < 0: # we have an overlay front
            if distance_along_door < -carcass_thickness or distance_along_door > 0:
                return False
        else: # we have an inset front
            if distance_along_door < 0 or distance_along_door > 0.6:
                return False

        carcass_edge = edge
        return True

    find_perpendicular_face(front_face, check_face)
    return carcass_edge

def longest_and_adjecent_edge_of_face(face: adsk.fusion.BRepFace) -> tuple[adsk.fusion.BRepEdge, adsk.fusion.BRepEdge]:
    loop = next(l for l in face.loops if l.isOuter)
    longest_edge = sorted(loop.edges, key=lambda e: e.length, reverse=True)[0]
    next_edge = adjecent_edge(longest_edge, face)
    return (longest_edge, next_edge)

def outer_edges_of_face(face: adsk.fusion.BRepFace) -> list[adsk.fusion.BRepEdge]:
    loop = next((x for x in face.loops if x.isOuter), None)
    assert(loop is not None)
    return fusion.as_list(loop.edges)

def vertices_of_face(face: adsk.fusion.BRepFace) -> list[adsk.fusion.BRepVertex]:
    edges = outer_edges_of_face(face)
    vertices = []
    for edge in edges:
        if edge.startVertex not in vertices: 
            vertices.append(edge.startVertex)
        if edge.endVertex not in vertices: 
            vertices.append(edge.endVertex)
    return vertices

def common_face_of_edges(edges: list[adsk.fusion.BRepEdge]) -> adsk.fusion.BRepFace:
    faces = [fusion.as_list(edge.faces) for edge in edges]
    result = faces[0]
    for x in faces[1:]:
        result = misc.intersect_lists(result, x)
    return result[0]

def common_face_of_vertices(vertices: list[adsk.fusion.BRepVertex]) -> adsk.fusion.BRepFace:
    faces = [fusion.as_list(v.faces) for v in vertices]
    result = faces[0]
    for x in faces[1:]:
        result = misc.intersect_lists(result, x)
    return result[0]

def normal_along_edge(edge: adsk.fusion.BRepEdge) -> Vector3D:
    result = edge.endVertex.geometry.asVector()
    result.subtract(edge.startVertex.geometry.asVector())
    result.normalize()
    return result

def fillet_cut_body(point: Point3D, leg1: Vector3D, leg2: Vector3D, fillet_radius: float, cut: Vector3D) -> adsk.fusion.BRepBody:
    mgr = adsk.fusion.TemporaryBRepManager.get()
    leg1 = vector.normalized(leg1)
    leg2 = vector.normalized(leg2)
    angle = math.acos(leg1.dotProduct(leg2))
    cylinder_mid_distance = fillet_radius/math.sin(angle/2)
    cylinder_leg_distance = fillet_radius/math.tan(angle/2)
    cyl1 = leg1.copy()
    cyl1.add(leg2)
    cyl1.scaleBy(0.5)
    cyl1.normalize()
    cyl1.scaleBy(cylinder_mid_distance)
    cyl1.add(point.asVector())
    cyl2 = cyl1.copy()
    cyl2.add(cut)
    cyl = mgr.createCylinderOrCone(cyl1.asPoint(), fillet_radius, cyl2.asPoint(), fillet_radius)
    cut_cyl1 = point.copy()
    cut_cyl2 = point.copy()
    cut_cyl2.translateBy(cut)
    cut_cyl = mgr.createCylinderOrCone(cut_cyl1, cylinder_leg_distance, cut_cyl2, cylinder_leg_distance)
    mgr.booleanOperation(cut_cyl, cyl, adsk.fusion.BooleanTypes.DifferenceBooleanType) # type: ignore
    return cut_cyl

# Creates an isosceles triangle in the xy plane. Base is along x, origin is at mid-base, thickness is in positive z.
def isosceles_triangle(width: float, height: float, thickness: float, fillet_radius: float = 0) -> adsk.fusion.BRepBody:
    mgr = adsk.fusion.TemporaryBRepManager.get()
    alpha = math.atan(height/(width/2))
    leg_length = height / math.sin(alpha)
    rectangle_extent = math.sin(alpha) * width

    trim_bb = adsk.core.OrientedBoundingBox3D.create(Point3D.create(100, height/2, thickness/2), Vector3D.create(1, 0, 0), Vector3D.create(0, 1, 0), 200, height, thickness)
    trim_body = mgr.createBox(trim_bb)

    bounding_box = adsk.core.OrientedBoundingBox3D.create(Point3D.create(0, 0, 0), Vector3D.create(1, 0, 0), Vector3D.create(0, 1, 0), leg_length, rectangle_extent, thickness)
    box = mgr.createBox(bounding_box)
    mgr.transform(box, matrix.translation_matrix(Vector3D.create(leg_length/2, -rectangle_extent/2, thickness/2)))
    mgr.transform(box, matrix.rotation_matrix(alpha, Vector3D.create(0, 0, -1), Point3D.create()))
    mgr.transform(box, matrix.translation_matrix(Vector3D.create(0, height, 0)))

    if fillet_radius > 0:
        fillet1 = fillet_cut_body(Point3D.create(width/2, 0, 0), Vector3D.create(-width/2, 0, 0), Vector3D.create(-width/2, height, 0), fillet_radius, Vector3D.create(0, 0, thickness))
        mgr.booleanOperation(box, fillet1, adsk.fusion.BooleanTypes.DifferenceBooleanType) # type: ignore
        fillet2 = fillet_cut_body(Point3D.create(0, height, 0), Vector3D.create(-width/2, -height, 0), Vector3D.create(width/2, -height, 0), fillet_radius, Vector3D.create(0, 0, thickness))
        mgr.booleanOperation(box, fillet2, adsk.fusion.BooleanTypes.DifferenceBooleanType) # type: ignore

    mgr.booleanOperation(box, trim_body, adsk.fusion.BooleanTypes.IntersectionBooleanType) # type: ignore
    box2 = mgr.copy(box)
    mgr.transform(box2, matrix.mirror_matrix(Point3D.create(), Vector3D.create(-1, 1, 1)))
    mgr.booleanOperation(box, box2, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore
    return box

def rectangle(width: float, height: float, thickness: float) -> adsk.fusion.BRepBody:
    x = Vector3D.create(1, 0, 0)
    y = Vector3D.create(0, 1, 0)
    bb = OrientedBoundingBox3D.create(Point3D.create(0, 0, thickness/2), x, y, width, height, thickness)
    mgr = adsk.fusion.TemporaryBRepManager.get()
    return mgr.createBox(bb)

# Creates a rounded rectangle in the xy plane. Width is along x, height along y, origin is at the center. Thickness is in positive z.
def rounded_rectangle(width: float, height: float, thickness: float, fillet_radius: float = 0) -> adsk.fusion.BRepBody:
    mgr = adsk.fusion.TemporaryBRepManager.get()
    box = union([
        rectangle(width - 2*fillet_radius, height, thickness),
        rectangle(width, height - 2*fillet_radius, thickness)
    ])
    if fillet_radius > 0:
        cyl = cylinder(fillet_radius, thickness)
        fillet_points = [
            Vector3D.create(-width/2+fillet_radius, height/2-fillet_radius, 0),
            Vector3D.create(width/2-fillet_radius, height/2-fillet_radius, 0),
            Vector3D.create(width/2-fillet_radius, -height/2+fillet_radius, 0),
            Vector3D.create(-width/2+fillet_radius, -height/2+fillet_radius, 0),
        ]
        for p in fillet_points:
            mgr.booleanOperation(box, transformed(cyl, matrix.translation_matrix(p)), adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore
    return box

# Creates a rhombus, origin as at its center, width is along x, height along y. 
def rhombus(width: float, height: float, thickness: float, fillet_radius: float = 0) -> adsk.fusion.BRepBody:
    mgr = adsk.fusion.TemporaryBRepManager.get()
    small_angle = math.atan(width/height) * 2
    leg_length = width/2 / math.sin(small_angle/2)
    box_width = math.sin(small_angle) * leg_length
    box_height = math.cos(small_angle/2) * height
    bb = OrientedBoundingBox3D.create(Point3D.create(), Vector3D.create(1, 0, 0), Vector3D.create(0, 1, 0), box_width, box_height, thickness)
    box = mgr.createBox(bb)
    box2 = mgr.copy(box)
    mgr.transform(box, matrix.rotation_matrix(small_angle/2, Vector3D.create(0, 0, 1), Point3D.create(0, 0, 0)))
    mgr.transform(box2, matrix.rotation_matrix(-small_angle/2, Vector3D.create(0, 0, 1), Point3D.create(0, 0, 0)))
    mgr.booleanOperation(box, box2, adsk.fusion.BooleanTypes.IntersectionBooleanType) # type: ignore
    if fillet_radius > 0:
        cut1 = fillet_cut_body(Point3D.create(0, height/2, -thickness/2), Vector3D.create(-width/2, -height/2, 0), Vector3D.create(width/2, -height/2, 0), fillet_radius, Vector3D.create(0, 0, thickness))    
        mgr.booleanOperation(box, cut1, adsk.fusion.BooleanTypes.DifferenceBooleanType) # type: ignore
        mgr.transform(cut1, matrix.mirror_matrix(Point3D.create(), Vector3D.create(1, -1, 1)))
        mgr.booleanOperation(box, cut1, adsk.fusion.BooleanTypes.DifferenceBooleanType) # type: ignore
        cut2 = fillet_cut_body(Point3D.create(-width/2, 0, -thickness/2), Vector3D.create(width/2, height/2, 0), Vector3D.create(width/2, -height/2, 0), fillet_radius, Vector3D.create(0, 0, thickness))
        mgr.booleanOperation(box, cut2, adsk.fusion.BooleanTypes.DifferenceBooleanType) # type: ignore
        mgr.transform(cut2, matrix.mirror_matrix(Point3D.create(), Vector3D.create(-1, 1, 1)))
        mgr.booleanOperation(box, cut2, adsk.fusion.BooleanTypes.DifferenceBooleanType) # type: ignore
    return box

# Creates a cylinder with the cylinder's lower circle's center at origin, height is positive z.
def cylinder(radius: float, height: float) -> adsk.fusion.BRepBody:
    mgr = adsk.fusion.TemporaryBRepManager.get()
    return mgr.createCylinderOrCone(Point3D.create(), radius, Point3D.create(0, 0, height), radius)
    
# Creates a slot with the length along x, thickness positive in z. Origin is at the center bottom of the first cylinder.
def slot(length: float, radius: float, thickness: float) -> adsk.fusion.BRepBody:
    mgr = adsk.fusion.TemporaryBRepManager.get()
    cyl1 = cylinder(radius, thickness)
    cyl1 = transformed(cyl1, matrix.translation_matrix(Vector3D.create(-length/2, 0, -thickness/2)))
    cyl2 = transformed(cyl1, matrix.translation_matrix(Vector3D.create(length, 0, 0)))
    box = mgr.createBox(adsk.core.OrientedBoundingBox3D.create(adsk.core.Point3D.create(), adsk.core.Vector3D.create(1, 0, 0), adsk.core.Vector3D.create(0, 1, 0), length, radius * 2, thickness ))
    mgr.booleanOperation(box, cyl1, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore
    mgr.booleanOperation(box, cyl2, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore
    mgr.transform(box, matrix.translation_matrix(Vector3D.create(length/2, 0, thickness/2)))
    return box

def transformed(body: adsk.fusion.BRepBody, transform: Matrix3D) -> adsk.fusion.BRepBody:
    mgr = adsk.fusion.TemporaryBRepManager.get()
    copy = mgr.copy(body)
    mgr.transform(copy, transform)
    return copy

def union(bodies: list[adsk.fusion.BRepBody]) -> adsk.fusion.BRepBody:
    mgr = adsk.fusion.TemporaryBRepManager.get()
    result = mgr.copy(bodies[0])
    for body in bodies[1:]:
        mgr.booleanOperation(result, body, adsk.fusion.BooleanTypes.UnionBooleanType) # type: ignore
    return result

def subtract(b1: adsk.fusion.BRepBody, b2: adsk.fusion.BRepBody) -> adsk.fusion.BRepBody:
    mgr = adsk.fusion.TemporaryBRepManager.get()
    result = mgr.copy(b1)
    mgr.booleanOperation(result, b2, adsk.fusion.BooleanTypes.DifferenceBooleanType) # type: ignore
    return result

# Constructs a right handed coordinate system on the face with the z axis pointing away from the body. The origin is either at the edges start or end vertex in order for positive z and y to point into the face's boundaries.
def coordinate_system_on_face(face: adsk.fusion.BRepFace, edge: adsk.fusion.BRepEdge) -> tuple[Point3D, Vector3D, Vector3D, Vector3D]:
    origin = edge.startVertex.geometry
    face_normal_into_body = normal_towards_face(face, get_opposite_face(face))
    x = normal_along_edge(edge)
    y = normal_into_face(edge, face)
    z = x.crossProduct(y)
    # Make sure we have a right hand coordinate system with z pointing away from the body, otherwise flip the x axis.
    if vector.dot_product(z, face_normal_into_body) > 0:
        origin = edge.endVertex.geometry
        x.scaleBy(-1)
        z = x.crossProduct(y)
    return (origin, x, y, z)

def coordinate_system_into_face(face: adsk.fusion.BRepFace, z: Vector3D) -> tuple[Point3D, Vector3D, Vector3D, Vector3D]:
    """
    Creates a right-handed coordinate system on the face, so that x is along the long edge, y points towards the center of the face, z points along cut
    """
    long_edge, _ = longest_and_adjecent_edge_of_face(face)
    # y is from the longest_edge into the face
    y = normal_into_face(long_edge, face)
    # z points down into the body
    z = vector.normalized(z)
    x = y.crossProduct(z)
    origin = long_edge.startVertex.geometry
    # if x, computed by y and z, doesn't lign up with the long_edge normal (which is derived from the edge's start to end points), we have to set the origin to the end point
    if vector.dot_product(x, normal_along_edge(long_edge)) < 0:
        origin = long_edge.endVertex.geometry
    return origin , x, y, z
    
def project_point_onto_edge(point: Point3D, edge: adsk.fusion.BRepEdge) -> Point3D:
    _, param = edge.evaluator.getParameterAtPoint(point)
    _, projected_point = edge.evaluator.getPointAtParameter(param)
    return projected_point

def project_point_onto_face(point: Point3D, face: adsk.fusion.BRepFace) -> Point3D:
    _, param = face.evaluator.getParameterAtPoint(point)
    _, projected_point = face.evaluator.getPointAtParameter(param)
    return projected_point

def closest_parallel_edge_of_face(edge: adsk.fusion.BRepEdge, face: adsk.fusion.BRepFace) -> adsk.fusion.BRepEdge | None:
    face_edges = outer_edges_of_face(face)
    parallel_edges = [e for e in face_edges if is_parallel(edge, e)]
    if not parallel_edges:
        return None
    face_normal = normal_into_face(parallel_edges[0], face)
    distance = float('inf')
    reference = edge.startVertex.geometry.asVector()
    result: adsk.fusion.BRepEdge | None = None
    for e in parallel_edges:
        new_distance = abs(face_normal.dotProduct(vector.subtract(e.startVertex.geometry.asVector(), reference)))
        if new_distance < distance:
            distance = new_distance
            result = e
    assert(result is not None)
    return result

def place_body_on_face_at_positions(body: adsk.fusion.BRepBody, face: adsk.fusion.BRepFace, edge: adsk.fusion.BRepEdge, positions: list[Vector3D]) -> adsk.fusion.BRepBody:
    origin, x, y, _ = coordinate_system_on_face(face, edge)
    x_coords = [vector.subtract(p, origin.asVector()).dotProduct(x) for p in positions]
    groups = [transformed(body, matrix.translation_matrix(Vector3D.create(x, 0, 0))) for x in x_coords]
    result = union(groups)
    return transformed(result, matrix.transform_from_root(origin, x, y))


