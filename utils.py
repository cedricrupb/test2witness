import inspect
import argparse

# Argparser ----------------------------------------------------------------

def main(fn):
    signature = inspect.signature(fn)
    parser    = argparse.ArgumentParser(description = fn.__doc__)

    for name, arg in signature.parameters.items():
        argdef = [name]
        kwargdef = {}
        
        if arg.annotation is not inspect.Signature.empty:
            kwargdef["type"] = arg.annotation

        if arg.default is not inspect.Signature.empty:
            argdef[0]    = "--%s" % name
            kwargdef["default"] = arg.default

        parser.add_argument(*argdef, **kwargdef)
    
    args = parser.parse_args()
    return fn(**args.__dict__)

