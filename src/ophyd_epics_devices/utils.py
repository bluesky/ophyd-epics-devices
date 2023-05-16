from typing import get_type_hints


# Use with types, not instances
def get_type_hints_no_inheritance(cls):
    cls_hints = get_type_hints(cls)

    for base_cls in cls.__bases__:
        base_hints = get_type_hints(base_cls)
        for base_hint_names in base_hints.keys():
            if base_hint_names in cls_hints:
                del cls_hints[base_hint_names]
    return cls_hints
