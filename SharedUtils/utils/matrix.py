import adsk.core, adsk.fusion
from adsk.core import Point3D, Vector3D, Matrix3D
from . import brep, vector

def mirror_matrix(origin: Point3D, multiplier: Vector3D) -> Matrix3D:
    t = Matrix3D.create()
    x1 = Vector3D.create(1, 0, 0)
    y1 = Vector3D.create(0, 1, 0)
    z1 = Vector3D.create(0, 0, 1)
    x2 = x1.copy()
    y2 = y1.copy()
    z2 = z1.copy()
    x2.scaleBy(multiplier.x)
    y2.scaleBy(multiplier.y)
    z2.scaleBy(multiplier.z)
    t.setToAlignCoordinateSystems(
        origin, x1, y1, z1,
        origin, x2, y2, z2
    )
    return t

def translation_matrix(translation: Vector3D) -> Matrix3D:
    t = Matrix3D.create()
    t.translation = translation
    return t

def rotation_matrix(angle, axis: Vector3D, anchor: Point3D):
    t = Matrix3D.create()
    t.setToRotation(angle, axis, anchor)
    return t

def inverted_matrix(m: Matrix3D) -> Matrix3D:
    result = m.copy()
    result.invert()
    return result

def transform_from_root(origin: Point3D, axis1: Vector3D, axis2: Vector3D) -> Matrix3D:
    t = Matrix3D.create()
    axis3 = axis1.crossProduct(axis2)
    axis3.normalize()
    zero = Point3D.create()
    x = Vector3D.create(1, 0, 0)
    y = Vector3D.create(0, 1, 0)
    z = Vector3D.create(0, 0, 1)
    t.setToAlignCoordinateSystems(
        zero, x, y, z,
        origin, axis1, axis2, axis3,
    )
    return t

def transform_to_root(origin: Point3D, axis1: Vector3D, axis2: Vector3D) -> Matrix3D:
    t = Matrix3D.create()
    axis3 = axis1.crossProduct(axis2)
    axis3.normalize()
    zero = Point3D.create()
    x = Vector3D.create(1, 0, 0)
    y = Vector3D.create(0, 1, 0)
    z = Vector3D.create(0, 0, 1)
    t.setToAlignCoordinateSystems(
        origin, axis1, axis2, axis3,
        zero, x, y, z,
    )
    return t

def combine_transforms(ts: list[Matrix3D]) -> Matrix3D:
    result = ts[0]
    for t in ts[1:]:
        result.transformBy(t)
    return result

