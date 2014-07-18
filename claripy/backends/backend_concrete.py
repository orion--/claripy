import logging
l = logging.getLogger("claripy.backends.backend_concrete")

from .backend import Backend, ops, BackendError
from .. import bv

class BackendConcrete(Backend):
    def __init__(self):
        Backend.__init__(self)
        self._make_raw_ops(set(ops) - { 'BitVec' }, op_module=bv)
        self._op_expr['BitVec'] = self.BitVec

    def BitVec(self, name, size, model=None): #pylint:disable=W0613,R0201
        if model is None:
            l.debug("BackendConcrete can only handle BitVec when we are given a model")
            raise BackendError("BackendConcrete can only handle BitVec when we are given a model")
        else:
            return model[name]

    def process_arg(self, e, model=None):
        if isinstance(e, E):
            if e.symbolic:
                l.debug("BackendConcrete.process_args() aborting on symbolic expression")
                raise BackendError("BackendConcrete.process_args() aborting on symbolic expression")

            a = e.eval()
        else:
            a = e

        if type(a) is None:
            l.debug("BackendConcrete doesn't handle abstract stuff")
            raise BackendError("BackendConcrete doesn't handle abstract stuff")

        if hasattr(a, '__module__') and a.__module__ == 'z3':
            if hasattr(a, 'as_long'):
                return bv.BVV(a.as_long(), a.size())
            else:
                l.warning("TODO: support more complex non-symbolic expressions, maybe?")
                raise BackendError("TODO: support more complex non-symbolic expressions, maybe?")
        else:
            return a

    def abstract(self, e, split_on=None):
        if type(e._obj) in (bv.BVV, int, long, str, float):
            return e._obj

        l.debug("%s unable to abstract %s", self.__class__, e._obj.__class__)
        raise BackendError("unable to abstract non-concrete stuff")

from ..expression import E
