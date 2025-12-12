from typing import cast
import adsk.core, adsk.fusion
from dataclasses import dataclass, field
import utils
from enum import Enum

class Operation(Enum):
    CUT = 1
    JOIN = 2
    INTERSECT = 3

    @property
    def feature_operation(self) -> adsk.fusion.FeatureOperations:
        match self:
            case Operation.CUT:
                return adsk.fusion.FeatureOperations.CutFeatureOperation # type: ignore
            case Operation.JOIN:
                return adsk.fusion.FeatureOperations.JoinFeatureOperation # type: ignore
            case Operation.INTERSECT:
                return adsk.fusion.FeatureOperations.IntersectFeatureOperation # type: ignore

@dataclass
class Combine:
    target_body: adsk.fusion.BRepBody
    tool_body: adsk.fusion.BRepBody
    operation: Operation

@dataclass
class TargetCombines:
    _cut_bodies: list[adsk.fusion.BRepBody] = field(default_factory=list)
    _join_bodies: list[adsk.fusion.BRepBody] = field(default_factory=list)
    _intersect_bodies: list[adsk.fusion.BRepBody] = field(default_factory=list)

    target_body: adsk.fusion.BRepBody | None = None

    @classmethod
    def from_combines(cls, combines: list[Combine], base_component: adsk.fusion.Component) -> tuple[list['TargetCombines'], list['TargetCombines']]:
        inside_component: dict[str, TargetCombines] = {}
        outside_component: dict[str, TargetCombines] = {}
        for comb in combines:
            target_dict = inside_component if comb.target_body.parentComponent == base_component else outside_component
            target_combines = target_dict.setdefault(comb.target_body.entityToken, cls())
            target_combines.add(comb)
        return (list(inside_component.values()), list(outside_component.values()))

    def add(self, combine: Combine):
        if self.target_body:
            assert(self.target_body == combine.target_body)
        else:
            self.target_body = combine.target_body
        match combine.operation:
            case Operation.CUT:
                self._cut_bodies.append(combine.tool_body)
            case Operation.JOIN:
                self._join_bodies.append(combine.tool_body)
            case Operation.INTERSECT:
                self._intersect_bodies.append(combine.tool_body)

    @property
    def all_combines(self) -> dict[Operation, list[adsk.fusion.BRepBody]]:
        result: dict[Operation, list[adsk.fusion.BRepBody]] = {}
        if self._cut_bodies:
            result[Operation.CUT] = self._cut_bodies
        if self._join_bodies:
            result[Operation.JOIN] = self._join_bodies
        if self._intersect_bodies:
            result[Operation.INTERSECT] = self._intersect_bodies
        return result

    @property
    def component(self) -> adsk.fusion.Component:
        assert(self.target_body is not None)
        return self.target_body.parentComponent


def create_features_from_combines(component: adsk.fusion.Component, combines: list[Combine], feature: adsk.fusion.CustomFeature | None = None) -> tuple[list[adsk.fusion.Feature], list[adsk.fusion.Feature]]:
    combines_inside_component, combines_outside_component = TargetCombines.from_combines(combines, component)

    base_features: list[adsk.fusion.BaseFeature] = []
    for target in combines_inside_component + combines_outside_component:
        for _, tool_bodies in target.all_combines.items():
            base = component.features.baseFeatures.add()
            base.startEdit()
            for tool in tool_bodies:
                component.bRepBodies.add(tool, base)
            base.finishEdit()
            base_features.append(base)

    features_inside_component: list[adsk.fusion.Feature] = cast(list[adsk.fusion.Feature], base_features)
    features_outside_component: list[adsk.fusion.Feature] = []
    
    base_idx = 0

    def create_combine_features_for_target(target: TargetCombines) -> list[adsk.fusion.Feature]:
        assert(target.target_body is not None)
        result: list[adsk.fusion.Feature] = []
        for op, _ in target.all_combines.items():
            nonlocal base_idx
            base = base_features[base_idx]
            coll = utils.fusion.as_object_collection(base.bodies)
            combine_input = component.features.combineFeatures.createInput(target.target_body, coll)
            combine_input.operation = op.feature_operation
            combine_feature = component.features.combineFeatures.add(combine_input)
            result.append(combine_feature)
            base_idx += 1
        return result

    for target in combines_inside_component:
        features_inside_component += create_combine_features_for_target(target)
    for target in combines_outside_component:
        features_outside_component += create_combine_features_for_target(target)
    for idx, f in enumerate(features_outside_component):
        id = feature.name if feature else "<unknown>"
        f.name = f"custom-feature<{id}>-combine"
        if feature:
            feature.customNamedValues.addOrSetValue(f"external-combine-{idx}", f.entityToken)

    return (features_inside_component, features_outside_component)


def update_features_from_combines(combines: list[Combine], feature: adsk.fusion.CustomFeature):
    combines_inside_component, combines_outside_component = TargetCombines.from_combines(combines, feature.parentComponent)
    base_idx = 0
    for target in combines_inside_component + combines_outside_component:
        for _, tool_bodies in target.all_combines.items():
            base: adsk.fusion.BaseFeature = feature.features[base_idx]
            base.startEdit()
            for idx, tool in enumerate(tool_bodies):
                base.updateBody(base.bodies[idx], tool)
            base.finishEdit()
            base_idx += 1
