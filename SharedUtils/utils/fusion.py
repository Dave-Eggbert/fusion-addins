from typing import Callable, Optional, cast
import adsk.core, adsk.fusion
from adsk.core import Point3D
from . import misc
import traceback, inspect


def as_list(objs):
    return [objs.item(idx) for idx in range(objs.count)]

def as_object_collection(objs):
    return adsk.core.ObjectCollection.createWithArray(as_list(objs))

def traverse_occurrence_tree(occurence: Optional[adsk.fusion.Occurrence], process: Callable[[adsk.fusion.Occurrence | adsk.fusion.Component], bool]):
    """
    Traverses the occurrence tree, starting with occurrence, going depth first, then siblings, then up to parent and so on until the root is reached.

    occurence : The occurrence to start the search from. If None, starts from the root component.
    process : A function that takes an occurrence or the root component and returns True to stop the search, False to continue.
    """
    previous = None
    design = cast(adsk.fusion.Design, adsk.core.Application.get().activeProduct)
    root_component = design.rootComponent
    current: adsk.fusion.Occurrence | adsk.fusion.Component = occurence or root_component

    def search_down(occ) -> bool:
        # Search this component first
        if process(occ):
            return True

        # Recurse into children (occurrences)
        children = []
        if isinstance(occ, adsk.fusion.Occurrence):
            children = occ.childOccurrences
        else:
             children = occ.occurrences  # Root component case
        for occ in children:
            if occ == previous:
                continue
            if search_down(occ):
                return True

        return False

    while current:
        # 1. Search current + children
        if search_down(current):
            return 

        if current == root_component:
            break

        # 2. Move up to parent
        assert(isinstance(current, adsk.fusion.Occurrence))
        occ_ctx = current.assemblyContext
        child_occurrences = None
        if not occ_ctx:
            root = current.component.parentDesign.rootComponent
            child_occurrences = root.occurrences
            parent = root
        else:
            parent = occ_ctx
            child_occurrences = parent.childOccurrences       

        # 3. Search siblings in parent
        for sibling_occ in child_occurrences:
            if sibling_occ == current:
                continue
            if search_down(sibling_occ):
                return

        previous = current
        current = parent

    return None

def point_to_str(point: Point3D) -> str:
    return f'{point.x};{point.y};{point.z}'
    
def str_to_point(str: str) -> Point3D:
    comps = [float(x) for x in str.split(';')]
    return Point3D.create(comps[0], comps[1], comps[2])

def new_event_handler(handler, superclass):
	class EventHandler(superclass):
		def notify(self, eventArgs):
			try:
				handler(eventArgs)
			except:
				handleException()
	return EventHandler()

def log(message):
    userInterface = adsk.core.Application.get().userInterface
    textPalette = cast(adsk.core.TextCommandPalette, userInterface.palettes.itemById('TextCommands'))
    textPalette.writeText(message)

def handleException():
	frameInfo = inspect.stack()[1]
	prefix = ''
	if 'self' in frameInfo.frame.f_locals:
		prefix = frameInfo.frame.f_locals['self'].__class__.__name__ + '.'
	log(f'{prefix}{frameInfo.function}: {traceback.format_exc()}\n')


