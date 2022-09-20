import hashlib
from datetime import datetime, timezone
from typing import Any
from collections import namedtuple

# API methods ------

def create_empty_witness(program_path = None, specification_path = None, is_violation = True, producer = None, is_32 = False):
    witness = WitnessAutomaton()
    witness.witness_format_version = "1.0"
    witness.witness_type = "violation_witness" if is_violation else "correctness_witness"
    witness.producer = producer or "Test2Witness"
    witness.architecture = "32bit" if is_32 else "64bit"

    if program_path is not None:
        witness.sourcecodelang = "Java" if program_path.endswith("java") else "C"
        witness.programfile  = program_path
        witness.programhash  = _hash(program_path)
       
    if specification_path is not None:
        with open(specification_path, "r") as i:
            witness.specification = "".join([
                line for line in i.readlines()
                if not line.startswith("//")
            ])

    witness.creationtime = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    return witness


def _hash(program_path):
    h = hashlib.sha256()
    with open(program_path, "rb") as i:
        h.update(i.read())
    return h.hexdigest()

# Objects --------

class AttributedObject:

    def __init__(self):
        self._attrs = {}

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_") or not hasattr(self, "_attrs"): 
            return super().__setattr__(name, value)
        self._attrs[name] = value
    
    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or not hasattr(self, "_attrs"): 
            return getattr(super(), name)
        try:
            return self._attrs[name]
        except KeyError:
            raise TypeError("Attribute %s is not defined" % name)


class ProgramState(AttributedObject):
    
    def __init__(self, node_id):
        self.node_id = node_id
        super().__init__()

class Edge(AttributedObject):

    def __init__(self, edge_id, src_node, target_node):
        self.edge_id     = edge_id
        self.src_node    = src_node
        self.target_node = target_node  
        super().__init__()


class WitnessAutomaton(AttributedObject):
    
    def __init__(self):
        self._nodes = {}
        self._edges = {}
        
        super().__init__()

    def node(self, node_id = None):
        if node_id is None: node_id = "N%d" % len(self._nodes)
        
        if node_id not in self._nodes:
            self._nodes[node_id] = ProgramState(node_id)
        
        return self._nodes[node_id]

    def edge(self, src_node, target_node, edge_id = None):
        if edge_id is None: edge_id = "E%d" % len(self._edges)

        if not isinstance(src_node, ProgramState):
            src_node = self.node(src_node)
        
        if not isinstance(target_node, ProgramState):
            target_node = self.node(target_node)

        if edge_id not in self._edges:
            self._edges[edge_id] = Edge(edge_id, src_node, target_node)
        
        edge = self._edges[edge_id]
        assert edge.src_node == src_node and edge.target_node == target_node

        return edge

    def toxml(self, output_path = None):
        output = [
            '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
            '<graphml xmlns="http://graphml.graphdrawing.org/xmlns" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        ]

        for attr in _collect_all_attrs(self):
            output.append(
                f' <key attr.name="{attr.name}" attr.type="{attr.type}" for="{attr.for_type}" id="{attr.id}"/>'
            )
        
        output.append(' <graph edgedefault="directed">')

        for key, value in self._attrs.items():
            key = key.replace("_", "-")
            if isinstance(value, bool): value = str(value).lower()
            output.append(f'  <data key="{key}">{value}</data>')
        
        registered_nodes = set()

        def add_node(node):
            if node.node_id in registered_nodes: return
            registered_nodes.add(node.node_id)
            if len(node._attrs) == 0:
                output.append(f'  <node id="{node.node_id}"/>')
            else:
                output.append(f'  <node id="{node.node_id}">')
                for key, value in node._attrs.items():
                    if value is None: continue
                    key = key.replace("_", ".")
                    if isinstance(value, bool): value = str(value).lower()
                    output.append(f'   <data key="{key}">{value}</data>')
                output.append('  </node>')

        for edge in self._edges.values():
            add_node(edge.src_node)
            add_node(edge.target_node)

            if len(edge._attrs) == 0:
                output.append(f'  <edge source="{edge.src_node.node_id}" target="{edge.target_node.node_id}" />')
            else:
                output.append(f'  <edge source="{edge.src_node.node_id}" target="{edge.target_node.node_id}">')
                for key, value in edge._attrs.items():
                    if value is None: continue
                    key = key.replace("_", ".")
                    output.append(f'   <data key="{key}">{value}</data>')
                output.append('  </edge>')

        output.append("</graph>")
        output.append("</graphml>")

        output = "\n".join(output)

        if output_path is None: return output

        with open(output_path, "w") as o:
            o.write(output)


Attribute = namedtuple("Attribute", ("name", "type", "for_type", "id"))

type_dict = {
    "str": "string",
    "int": "int",
    "bool": "boolean"
}

def _collect_attrs_from_list(object_type, objects):
    attrs = []
    object_attrs = set.union(*[set(o._attrs.keys()) for o in objects])

    for key in object_attrs:
        key_types = set([type(o._attrs.get(key, None)) for o in objects])
        key_types.discard(type(None))
        if len(key_types) == 0: continue

        assert len(key_types) == 1
        value_type = type_dict[next(iter(key_types)).__name__]
        key_id = key.replace("_", ".")
        attrs.append(Attribute(key, value_type, object_type, key_id))

    return attrs


def _collect_all_attrs(witness):
    attrs = []

    for key, value in witness._attrs.items():
        value_type = type_dict[type(value).__name__]
        key_id = key.replace("_", "-")
        attrs.append(Attribute(key, value_type, "graph", key_id))

    attrs.extend(_collect_attrs_from_list("node", witness._nodes.values()))
    attrs.extend(_collect_attrs_from_list("edge", witness._edges.values()))
     
    return attrs
