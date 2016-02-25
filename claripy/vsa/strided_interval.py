import fractions
import functools
import math
import itertools
import logging

logger = logging.getLogger('claripy.vsa.strided_interval')

from ..backend_object import BackendObject

def reversed_processor(f):
    def processor(self, *args, **kwargs):
        if self._reversed:
            # Reverse it for real. We have to accept the precision penalty.
            reversed = self._reverse()
            return f(reversed, *args, **kwargs)
        return f(self, *args, **kwargs)

    return processor

def normalize_types(f):
    @functools.wraps(f)
    def normalizer(self, o):
        '''
        Convert any object to an object that we can process.
        '''

        # Special handler for union
        if f.__name__ == 'union' and isinstance(o, DiscreteStridedIntervalSet):
            return o.union(self)

        if isinstance(o, ValueSet) or isinstance(o, DiscreteStridedIntervalSet):
            # It should be put to o.__radd__(self) when o is a ValueSet
            return NotImplemented

        if isinstance(o, Base) or isinstance(self, Base):
            return NotImplemented
        if type(self) is BVV:
            self = self.value
        if type(o) is BVV:
            o = o.value
        if type(o) in (int, long):
            min_bits_required = 64
            if isinstance(self, StridedInterval):
                min_bits_required = self.bits
            o = StridedInterval(bits=StridedInterval.min_bits(o, max_bits=min_bits_required), stride=0, lower_bound=o,
                                upper_bound=o)
        if type(self) in (int, long):
            min_bits_required = 64
            if isinstance(o, StridedInterval):
                min_bits_required = o.bits
            self = StridedInterval(bits=StridedInterval.min_bits(self, max_bits=min_bits_required), stride=0,
                                   lower_bound=self, upper_bound=self)

        if f.__name__ not in ('concat', ):
            # Make sure they have the same length
            common_bits = max(o.bits, self.bits)
            if o.bits < common_bits:
                o = o.agnostic_extend(common_bits)
            if self.bits < common_bits:
                self = self.agnostic_extend(common_bits)

        self_reversed = False

        if self._reversed != o._reversed:
            # We are working on two instances that have different endianness!
            # Make sure the `reversed` property of self is kept the same after operation
            if self._reversed:
                if o.is_integer:
                    o = o._reverse()
                else:
                    self_reversed = True
                    self = self._reverse()

            else:
                # If self is an integer, we wanna reverse self as well
                if self.is_integer:
                    self = self._reverse()
                    self_reversed = True
                else:
                    o = o._reverse()

        ret = f(self, o)
        if self_reversed and isinstance(ret, StridedInterval):
            ret = ret.reverse()
        return ret

    return normalizer

si_id_ctr = itertools.count()

# Whether DiscreteStridedIntervalSet should be used or not. Sometimes we manually set it to False to allow easy
# implementation of test cases.
allow_dsis = False

class WarrenMethods(object):
    """
        Methods as suggested in book.
        Hackers Delight.
    """
    @staticmethod
    def min_or(a, b, c, d, w):
        """
        Lower bound of result of ORing 2-intervals
        :param a: Lower bound of first interval
        :param b: Upper bound of first interval
        :param c: Lower bound of second interval
        :param d: Upper bound of second interval
        :param w: bit width
        :return: Lower bound of ORing 2-intervals
        """
        m = (1 << (w - 1))
        while m != 0:
            if ((~a) & c & m) != 0:
                temp = (a | m) & -m
                if temp <= b:
                    a = temp
                    break
            elif (a & (~c) & m) != 0:
                temp = (c | m) & -m
                if temp <= d:
                    c = temp
                    break
            m >>= 1
        return a | c

    @staticmethod
    def max_or(a, b, c, d, w):
        """
        Upper bound of result of ORing 2-intervals
        :param a: Lower bound of first interval
        :param b: Upper bound of first interval
        :param c: Lower bound of second interval
        :param d: Upper bound of second interval
        :param w: bit width
        :return: Upper bound of ORing 2-intervals
        """
        m = (1 << (w - 1))
        while m != 0:
            if (b & d & m) != 0:
                temp = (b - m) | (m - 1)
                if temp >= a:
                    b = temp
                    break
                temp = (d - m) | (m - 1)
                if temp >= c:
                    d = temp
                    break
            m >>= 1
        return b | d

    @staticmethod
    def min_and(a, b, c, d, w):
        """
        Lower bound of result of ANDing 2-intervals
        :param a: Lower bound of first interval
        :param b: Upper bound of first interval
        :param c: Lower bound of second interval
        :param d: Upper bound of second interval
        :param w: bit width
        :return: Lower bound of ANDing 2-intervals
        """
        m = (1 << (w - 1))
        while m != 0:
            if (~a & ~c & m) != 0:
                temp = (a | m) & -m
                if temp <= b:
                    a = temp
                    break
                temp = (c | m) & -m
                if temp <= d:
                    c = temp
                    break
            m >>= 1
        return a & c

    @staticmethod
    def max_and(a, b, c, d, w):
        """
        Upper bound of result of ANDing 2-intervals
        :param a: Lower bound of first interval
        :param b: Upper bound of first interval
        :param c: Lower bound of second interval
        :param d: Upper bound of second interval
        :param w: bit width
        :return: Upper bound of ANDing 2-intervals
        """
        m = (1 << (w - 1))
        while m != 0:
            if ((~d) & b & m) != 0:
                temp = (b & ~m) | (m - 1)
                if temp >= a:
                    b = temp
                    break
            elif (d & (~b) & m) != 0:
                temp = (d & ~m) | (m - 1)
                if temp >= c:
                    d = temp
                    break
            m >>= 1
        return b & d

    @staticmethod
    def min_xor(a, b, c, d, w):
        """
        Lower bound of result of XORing 2-intervals
        :param a: Lower bound of first interval
        :param b: Upper bound of first interval
        :param c: Lower bound of second interval
        :param d: Upper bound of second interval
        :param w: bit width
        :return: Lower bound of XORing 2-intervals
        """
        m = (1 << (w - 1))
        while m != 0:
            if ((~a) & c & m) != 0:
                temp = (a | m) & -m
                if temp <= b:
                    a = temp
            elif (a & (~c) & m) != 0:
                temp = (c | m) & -m
                if temp <= d:
                    c = temp
            m >>= 1
        return a ^ c

    @staticmethod
    def max_xor(a, b, c, d, w):
        """
        Upper bound of result of XORing 2-intervals
        :param a: Lower bound of first interval
        :param b: Upper bound of first interval
        :param c: Lower bound of second interval
        :param d: Upper bound of second interval
        :param w: bit width
        :return: Upper bound of XORing 2-intervals
        """
        m = (1 << (w - 1))
        while m != 0:
            if (b & d & m) != 0:
                temp = (b - m) | (m - 1)
                if temp >= a:
                    b = temp
                else:
                    temp = (d - m) | (m - 1)
                    if temp >= c:
                        d = temp
            m >>= 1
        return b ^ d


class StridedInterval(BackendObject):
    """
    A Strided Interval is represented in the following form:
        bits,stride[lower_bound, upper_bound]
    For more details, please refer to relevant papers like TIE and WYSINWYE.

    This implementation is signedness-agostic, please refer to _Signedness-Agnostic Program Analysis: Precise Integer
    Bounds for Low-Level Code_ by Jorge A. Navas, etc. for more details.

    Thanks all corresponding authors for their outstanding works.
    """
    def __init__(self, name=None, bits=0, stride=None, lower_bound=None, upper_bound=None, uninitialized=False, bottom=False):
        self._name = name

        if self._name is None:
            self._name = "SI_%d" % si_id_ctr.next()

        self._bits = bits
        self._stride = stride if stride is not None else 1
        self._lower_bound = lower_bound if lower_bound is not None else 0
        self._upper_bound = upper_bound if upper_bound is not None else (2**bits-1)

        if lower_bound is not None and type(lower_bound) not in (int, long):
            raise ClaripyVSAError("'lower_bound' must be an int or a long. %s is not supported." % type(lower_bound))

        if upper_bound is not None and type(upper_bound) not in (int, long):
            raise ClaripyVSAError("'upper_bound' must be an int or a long. %s is not supported." % type(upper_bound))

        self._reversed = False

        self._is_bottom = bottom

        self.uninitialized = uninitialized

        if self._upper_bound is not None and bits == 0:
            self._bits = self._min_bits()

        if self._upper_bound is None:
            self._upper_bound = StridedInterval.max_int(self.bits)

        if self._lower_bound is None:
            self._lower_bound = StridedInterval.min_int(self.bits)

        # For lower bound and upper bound, we always store the unsigned version
        self._lower_bound &= (2 ** bits - 1)
        self._upper_bound &= (2 ** bits - 1)

        self.normalize()

    def copy(self):
        si = StridedInterval(name=self._name,
                             bits=self.bits,
                             stride=self.stride,
                             lower_bound=self.lower_bound,
                             upper_bound=self.upper_bound,
                             uninitialized=self.uninitialized,
                             bottom=self._is_bottom)
        si._reversed = self._reversed
        return si

    def nameless_copy(self):
        si = StridedInterval(name=None,
                             bits=self.bits,
                             stride=self.stride,
                             lower_bound=self.lower_bound,
                             upper_bound=self.upper_bound,
                             uninitialized=self.uninitialized,
                             bottom=self._is_bottom)
        si._reversed = self._reversed
        return si

    def normalize(self):
        if self.bits == 8 and self.reversed:
            self._reversed = False

        if self.is_empty:
            return self

        if self.lower_bound == self.upper_bound:
            self._stride = 0

        if self.lower_bound < 0:
            self.lower_bound = self.lower_bound & (2 ** self.bits - 1)

        self._normalize_top()

        if self._stride < 0:
            raise Exception("Why does this happen?")

        return self

    def eval(self, n, signed=False):
        """
        Evaluate this StridedInterval to obtain a list of concrete integers
        :param n: Upper bound for the number of concrete integers
        :param signed: Treat this StridedInterval as signed or unsigned
        :return: A list of at most `n` concrete integers
        """

        results = [ ]

        if self.is_empty:
            # no value is available
            pass

        elif self.stride == 0 and n > 0:
            results.append(self.lower_bound)
        else:
            if signed:
                # View it as a signed integer
                bounds = self._signed_bounds()

            else:
                # View it as an unsigned integer
                bounds = self._unsigned_bounds()

            for lb, ub in bounds:
                while len(results) < n and lb <= ub:
                    results.append(lb)
                    lb += self.stride # It will not overflow

        return results

    #
    # Private methods
    #

    def __hash__(self):
        return hash((self.bits, self.lower_bound, self.upper_bound, self.stride, self._reversed, self.uninitialized))

    def _normalize_top(self):
        if self.lower_bound == self._modular_add(self.upper_bound, 1, self.bits) and self.stride == 1:
            # This is a TOP!
            # Normalize it
            self.lower_bound = 0
            self.upper_bound = self.max_int(self.bits)

    def _ssplit(self):
        """
        Split `self` at the south pole, which is the same as in unsigned arithmetic

        :return: A list of split StridedIntervals
        """

        south_pole_right = self.max_int(self.bits) # 111...1
        # south_pole_left = 0

        # Is `self` straddling the south pole?
        if self.upper_bound < self.lower_bound:
            # It straddles the south pole!

            a_upper_bound = south_pole_right - ((south_pole_right - self.lower_bound) % self.stride)
            a = StridedInterval(bits=self.bits, stride=self.stride, lower_bound=self.lower_bound, upper_bound=a_upper_bound)

            b_lower_bound = self._modular_add(a_upper_bound, self.stride, self.bits)
            b = StridedInterval(bits=self.bits, stride=self.stride, lower_bound=b_lower_bound, upper_bound=self.upper_bound)

            return [ a, b ]

        else:
            return [ self.copy() ]

    def _nsplit(self):
        """
        Split `self` at the north pole, which is the same as in signed arithmetic

        :return: A list of split StridedIntervals
        """

        north_pole_left = self.max_int(self.bits - 1) # 01111...1
        north_pole_right = 2 ** (self.bits - 1) # 1000...0

        # Is `self` straddling the north pole?
        straddling = False
        if self.upper_bound >= north_pole_right:
            if self.lower_bound > self.upper_bound:
                # Yes it does!
                straddling = True
            elif self.lower_bound <= north_pole_left:
                straddling = True

        else:
            if self.lower_bound > self.upper_bound and self.lower_bound <= north_pole_left:
                straddling = True

        if straddling:
            a_upper_bound = north_pole_left - ((north_pole_left - self.lower_bound) % self.stride)
            a = StridedInterval(bits=self.bits, stride=self.stride, lower_bound=self.lower_bound, upper_bound=a_upper_bound)

            b_lower_bound = a_upper_bound + self.stride
            b = StridedInterval(bits=self.bits, stride=self.stride, lower_bound=b_lower_bound, upper_bound=self.upper_bound)

            return [ a, b ]

        else:
            return [ self.copy() ]

    def _psplit(self):
        """
        Split `self` at both north and south poles

        :return: A list of split StridedIntervals
        """

        nsplit_list = self._nsplit()
        psplit_list = [ ]

        for si in nsplit_list:
            psplit_list.extend(si._ssplit())

        return psplit_list

    def _signed_bounds(self):
        """
        Get lower bound and upper bound for `self` in signed arithmetic
        :return: a list  of (lower_bound, upper_bound) tuples
        """

        nsplit = self._nsplit()
        if len(nsplit) == 1:
            lb = nsplit[0].lower_bound
            ub = nsplit[0].upper_bound

            lb = self._unsigned_to_signed(lb, self.bits)
            ub = self._unsigned_to_signed(ub, self.bits)

            return [ (lb, ub) ]

        elif len(nsplit) == 2:
            # nsplit[0] is on the left hemisphere, and nsplit[1] is on the right hemisphere

            # The left one
            lb_1 = nsplit[0].lower_bound
            ub_1 = nsplit[0].upper_bound

            # The right one
            lb_2 = nsplit[1].lower_bound
            ub_2 = nsplit[1].upper_bound
            # Then convert them to negative numbers
            lb_2 = self._unsigned_to_signed(lb_2, self.bits)
            ub_2 = self._unsigned_to_signed(ub_2, self.bits)

            return [ (lb_1, ub_1), (lb_2, ub_2) ]
        else:
            raise Exception('WTF')

    def _unsigned_bounds(self):
        """
        Get lower bound and upper bound for `self` in unsigned arithmetic
        :return: a list of (lower_bound, upper_bound) tuples
        """

        ssplit = self._ssplit()
        if len(ssplit) == 1:
            lb = ssplit[0].lower_bound
            ub = ssplit[0].upper_bound

            return [ (lb, ub) ]
        elif len(ssplit) == 2:
            # ssplit[0] is on the left hemisphere, and ssplit[1] is on the right hemisphere

            lb_1 = ssplit[0].lower_bound
            ub_1 = ssplit[0].upper_bound

            lb_2 = ssplit[1].lower_bound
            ub_2 = ssplit[1].upper_bound

            return [ (lb_1, ub_1), (lb_2, ub_2) ]
        else:
            raise Exception('WTF')

    #
    # Comparison operations
    #

    def identical(self, o):
        """
        Used to make exact comparisons between two StridedIntervals. Usually it is only used in test cases.

        :param o: The other StridedInterval to compare with
        :return: True if they are exactly same, False otherwise
        """

        if (self.bits == o.bits and
                self.stride == o.stride and
                self.lower_bound == o.lower_bound and
                self.upper_bound == o.upper_bound):
            return True

        else:
            return False

    @normalize_types
    def SLT(self, o):
        """
        Signed less than

        :param o: The other operand
        :return: TrueResult(), FalseResult(), or MaybeResult()
        """

        signed_bounds_1 = self._signed_bounds()
        signed_bounds_2 = o._signed_bounds()

        ret = [ ]
        for lb_1, ub_1 in signed_bounds_1:
            for lb_2, ub_2 in signed_bounds_2:
                if ub_1 < lb_2:
                    ret.append(TrueResult())
                elif lb_1 >= ub_2:
                    ret.append(FalseResult())
                else:
                    ret.append(MaybeResult())

        if all(r.identical(TrueResult()) for r in ret):
            return TrueResult()
        elif all(r.identical(FalseResult()) for r in ret):
            return FalseResult()
        else:
            return MaybeResult()

    @normalize_types
    def SLE(self, o):
        """
        Signed less than or equal to

        :param o: The other operand
        :return: TrueResult(), FalseResult(), or MaybeResult()
        """

        signed_bounds_1 = self._signed_bounds()
        signed_bounds_2 = o._signed_bounds()

        ret = []
        for lb_1, ub_1 in signed_bounds_1:
            for lb_2, ub_2 in signed_bounds_2:
                if ub_1 <= lb_2:
                    ret.append(TrueResult())
                elif lb_1 > ub_2:
                    ret.append(FalseResult())
                else:
                    ret.append(MaybeResult())

        if all(r.identical(TrueResult()) for r in ret):
            return TrueResult()
        elif all(r.identical(FalseResult()) for r in ret):
            return FalseResult()
        else:
            return MaybeResult()

    @normalize_types
    def SGT(self, o):
        """
        Signed greater than
        :param o: The other operand
        :return: TrueResult(), FalseResult(), or MaybeResult()
        """

        signed_bounds_1 = self._signed_bounds()
        signed_bounds_2 = o._signed_bounds()

        ret = []
        for lb_1, ub_1 in signed_bounds_1:
            for lb_2, ub_2 in signed_bounds_2:
                if lb_1 > ub_2:
                    ret.append(TrueResult())
                elif ub_1 <= lb_2:
                    ret.append(FalseResult())
                else:
                    ret.append(MaybeResult())

        if all(r.identical(TrueResult()) for r in ret):
            return TrueResult()
        elif all(r.identical(FalseResult()) for r in ret):
            return FalseResult()
        else:
            return MaybeResult()

    @normalize_types
    def SGE(self, o):
        """
        Signed greater than or equal to
        :param o: The other operand
        :return: TrueResult(), FalseResult(), or MaybeResult()
        """

        signed_bounds_1 = self._signed_bounds()
        signed_bounds_2 = o._signed_bounds()

        ret = []
        for lb_1, ub_1 in signed_bounds_1:
            for lb_2, ub_2 in signed_bounds_2:
                if lb_1 >= ub_2:
                    ret.append(TrueResult())
                elif ub_1 < lb_2:
                    ret.append(FalseResult())
                else:
                    ret.append(MaybeResult())

        if all(r.identical(TrueResult()) for r in ret):
            return TrueResult()
        elif all(r.identical(FalseResult()) for r in ret):
            return FalseResult()
        else:
            return MaybeResult()

    @normalize_types
    def ULT(self, o):
        """
        Unsigned less than

        :param o: The other operand
        :return: TrueResult(), FalseResult(), or MaybeResult()
        """

        unsigned_bounds_1 = self._unsigned_bounds()
        unsigned_bounds_2 = o._unsigned_bounds()

        ret = []
        for lb_1, ub_1 in unsigned_bounds_1:
            for lb_2, ub_2 in unsigned_bounds_2:
                if ub_1 < lb_2:
                    ret.append(TrueResult())
                elif lb_1 >= ub_2:
                    ret.append(FalseResult())
                else:
                    ret.append(MaybeResult())

        if all(r.identical(TrueResult()) for r in ret):
            return TrueResult()
        elif all(r.identical(FalseResult()) for r in ret):
            return FalseResult()
        else:
            return MaybeResult()

    @normalize_types
    def ULE(self, o):
        """
        Unsigned less than or equal to

        :param o: The other operand
        :return: TrueResult(), FalseResult(), or MaybeResult()
        """

        unsigned_bounds_1 = self._unsigned_bounds()
        unsigned_bounds_2 = o._unsigned_bounds()

        ret = []
        for lb_1, ub_1 in unsigned_bounds_1:
            for lb_2, ub_2 in unsigned_bounds_2:
                if ub_1 <= lb_2:
                    ret.append(TrueResult())
                elif lb_1 > ub_2:
                    ret.append(FalseResult())
                else:
                    ret.append(MaybeResult())

        if all(r.identical(TrueResult()) for r in ret):
            return TrueResult()
        elif all(r.identical(FalseResult()) for r in ret):
            return FalseResult()
        else:
            return MaybeResult()

    @normalize_types
    def UGT(self, o):
        """
        Signed greater than
        :param o: The other operand
        :return: TrueResult(), FalseResult(), or MaybeResult()
        """

        unsigned_bounds_1 = self._unsigned_bounds()
        unsigned_bounds_2 = o._unsigned_bounds()

        ret = []
        for lb_1, ub_1 in unsigned_bounds_1:
            for lb_2, ub_2 in unsigned_bounds_2:
                if lb_1 > ub_2:
                    ret.append(TrueResult())
                elif ub_1 <= lb_2:
                    ret.append(FalseResult())
                else:
                    ret.append(MaybeResult())

        if all(r.identical(TrueResult()) for r in ret):
            return TrueResult()
        elif all(r.identical(FalseResult()) for r in ret):
            return FalseResult()
        else:
            return MaybeResult()

    @normalize_types
    def UGE(self, o):
        """
        Unsigned greater than or equal to
        :param o: The other operand
        :return: TrueResult(), FalseResult(), or MaybeResult()
        """

        unsigned_bounds_1 = self._unsigned_bounds()
        unsigned_bounds_2 = o._unsigned_bounds()

        ret = []
        for lb_1, ub_1 in unsigned_bounds_1:
            for lb_2, ub_2 in unsigned_bounds_2:
                if lb_1 >= ub_2:
                    ret.append(TrueResult())
                elif ub_1 < lb_2:
                    ret.append(FalseResult())
                else:
                    ret.append(MaybeResult())

        if all(r.identical(TrueResult()) for r in ret):
            return TrueResult()
        elif all(r.identical(FalseResult()) for r in ret):
            return FalseResult()
        else:
            return MaybeResult()

    @normalize_types
    def eq(self, o):
        """
        Equal

        :param o: The ohter operand
        :return: TrueResult(), FalseResult(), or MaybeResult()
        """

        if (self.is_integer
            and o.is_integer
            ):
            # Two integers
            if self.lower_bound == o.lower_bound:
                # They are equal
                return TrueResult()
            else:
                # They are not equal
                return FalseResult()

        else:
            if self.name == o.name:
                return TrueResult() # They are the same guy

            si_intersection = self.intersection(o).pop()
            if si_intersection.is_empty:
                return FalseResult()

            else:
                return MaybeResult()

    #
    # Overriding default operators in Python
    #

    def __len__(self):
        '''
        Get the length in bits of this variable.
        :return:
        '''
        return self._bits

    def __eq__(self, o):
        return self.eq(o)

    def __ne__(self, o):
        return ~(self.eq(o))

    def __gt__(self, other):
        """
        Unsigned greater than
        :param other: The other operand
        :return: TrueResult(), FalseResult(), or MaybeResult()
        """
        return self.UGT(other)

    def __ge__(self, other):
        """
        Unsigned greater than or equal to
        :param other: The other operand
        :return: TrueResult(), FalseResult(), or MaybeResult()
        """

        return self.UGE(other)

    def __lt__(self, other):
        """
        Unsigned less than
        :param other: The other operand
        :return: TrueResult(), FalseResult(), or MaybeResult()
        """
        return self.ULT(other)

    def __le__(self, other):
        """
        Unsigned less than or equal to
        :param other: The other operand
        :return: TrueResult(), FalseResult(), or MaybeResult()
        """
        return self.ULE(other)

    def __add__(self, o):
        return self.add(o)

    def __sub__(self, o):
        return self.sub(o)

    def __mul__(self, o):
        return self.mul(o)

    @normalize_types
    def __mod__(self, o):
        # TODO: Make a better approximation
        if self.is_integer and o.is_integer:
            r = self.lower_bound % o.lower_bound
            si = StridedInterval(bits=self.bits, stride=0, lower_bound=r, upper_bound=r)
            return si

        else:
            si = StridedInterval(bits=self.bits, stride=1, lower_bound=0, upper_bound=o.upper_bound - 1)
            return si

    @normalize_types
    def __div__(self, o):
        """
        Unsigned division
        :param o: The divisor
        :return: The quotient (self / o)
        """

        return self.udiv(o)

    def __neg__(self):
        return self.bitwise_not()

    def __invert__(self):
        return self.bitwise_not()

    @normalize_types
    def __or__(self, other):
        return self.bitwise_or(other)

    @normalize_types
    def __and__(self, other):
        return self.bitwise_and(other)

    def __rand__(self, other):
        return self.__and__(other)

    @normalize_types
    def __xor__(self, other):
        return self.bitwise_xor(other)

    def __rxor__(self, other):
        return self.__xor__(other)

    def __lshift__(self, other):
        return self.lshift(other)

    def __rshift__(self, other, preserve_sign=True):
        return self.rshift(other, preserve_sign=preserve_sign)

    def __repr__(self):
        s = ""
        if self.is_empty:
            s = '<%d>[EmptySI]' % (self._bits)
        else:
            lower_bound = self._lower_bound if type(self._lower_bound) == str else '%#x' % self._lower_bound
            upper_bound = self._upper_bound if type(self._upper_bound) == str else '%#x' % self._upper_bound
            s = '<%d>0x%x[%s, %s]%s' % (self._bits, self._stride,
                                          lower_bound, upper_bound,
                                          'R' if self._reversed else '')

        if self.uninitialized:
            s += "(uninit)"

        return s

    #
    # Properties
    #

    @property
    def name(self):
        return self._name

    @property
    def reversed(self):
        return self._reversed

    @property
    def size(self):
        logger.warning("StridedInterval.size will be deprecated soon. Please use StridedInterval.cardinality instead.")
        return self.cardinality

    @property
    def cardinality(self):
        if self.is_bottom:
            return 0
        elif self.is_integer:
            return 1
        else:
            return (self._modular_sub(self._upper_bound, self._lower_bound, self.bits) + self._stride) / self._stride

    @property
    def complement(self):
        """
        Return the complement of the interval
        Refer section 3.1 augmented for managing strides
        :return:
        """
        # case 1
        if self.is_empty:
            return StridedInterval.top(self.bits)
        # case 2
        if self.is_top:
            return StridedInterval.empty(self.bits)
        # case 3
        y_plus_1 = StridedInterval._modular_add(self.upper_bound, 1, self.bits)
        x_minus_1 = StridedInterval._modular_sub(self.lower_bound, 1, self.bits)

        # the new stride has to be the GCD between the old stride and the distance
        # between the new lower bound and the new upper bound. This assure that in
        # the new interval the boundaries are valid solution when the SI is
        # evaluated.
        dist = StridedInterval._wrapped_cardinality(y_plus_1, x_minus_1, self.bits) - 1

        # the new SI is an integer
        if dist < 0:
            new_stride = 0
        elif self._stride == 0:
            new_stride = 1
        else:
            new_stride = fractions.gcd(self._stride, dist)

        return StridedInterval(lower_bound=y_plus_1, upper_bound=x_minus_1, bits=self.bits, stride=new_stride)

    @property
    def lower_bound(self):
        return self._lower_bound

    @lower_bound.setter
    def lower_bound(self, value):
        self._lower_bound = value

    @property
    def upper_bound(self):
        return self._upper_bound

    @upper_bound.setter
    def upper_bound(self, value):
        self._upper_bound = value

    @property
    def bits(self):
        return self._bits

    @property
    def stride(self):
        return self._stride

    @stride.setter
    def stride(self, value):
        self._stride = value

    @property
    @reversed_processor
    def max(self):
        if not self.is_empty:
            return self.upper_bound
        else:
            # It is empty!
            return None

    @property
    @reversed_processor
    def min(self):
        if not self.is_empty:
            return self.lower_bound
        else:
            # It is empty
            return None

    @property
    def unique(self):
        return self.min is not None and self.min == self.max

    def _min_bits(self):
        v = self._upper_bound
        assert v >= 0
        return StridedInterval.min_bits(v)

    @property
    def is_empty(self):
        """
        The same as is_bottom
        :return: True/False
        """
        return self.is_bottom

    @property
    def is_top(self):
        '''
        If this is a TOP value
        :return: True if this is a TOP
        '''
        return (self.stride == 1 and
                self.lower_bound == self._modular_add(self.upper_bound, 1, self.bits)
                )

    @property
    def is_bottom(self):
        """
        Whether this StridedInterval is a BOTTOM, in other words, describes an empty set of integers
        :return: True/False
        """
        return self._is_bottom

    @property
    def is_integer(self):
        '''
        If this is an integer, i.e. self.lower_bound == self.upper_bound
        :return: True if this is an integer, False otherwise
        '''
        return self.lower_bound == self.upper_bound

    #
    # Modular arithmetic
    #

    @staticmethod
    def _modular_add(a, b, bits):
        return (a + b) % (2 ** bits)

    @staticmethod
    def _modular_sub(a, b, bits):
        return (a - b) % (2 ** bits)

    @staticmethod
    def _modular_mul(a, b, bits):
        return (a * b) % (2 ** bits)

    #
    # Helper methods
    #

    @staticmethod
    def lcm(a, b):
        """
        Get the least common multiple
        :param a: The first operand (integer)
        :param b: The second operand (integer)
        :return: Their LCM
        """
        return a * b // fractions.gcd(a, b)

    @staticmethod
    def gcd(a, b):
        """
        Get the greatest common divisor
        :param a: The first operand (integer)
        :param b: The second operand (integer)
        :return: Their GCD
        """

        return fractions.gcd(a, b)

    @staticmethod
    def highbit(k):
        return 1 << (k - 1)

    @staticmethod
    def min_bits(val, max_bits=None):
        if val == 0:
            return 1
        elif val < 0:
            if max_bits is None:
                return int(math.log(-val, 2) + 1) + 1
            else:
                assert isinstance(max_bits, int)
                return int(math.log((((1 << max_bits) - 1) & ~(-val)) + 1, 2) + 1)
        else:
            # Here we assume the maximum val is 64 bits
            # Special case to deal with the floating-point imprecision
            if val > 0xfffffffffffe0000 and val <= 0x10000000000000000:
                return 64
            return int(math.log(val, 2) + 1)

    @staticmethod
    def max_int(k):
        # return StridedInterval.highbit(k + 1) - 1
        return StridedInterval.highbit(k + 1) - 1

    @staticmethod
    def min_int(k):
        return -StridedInterval.highbit(k)

    @staticmethod
    def sign_max_int(k):
        return 2 ** (k - 1) - 1

    @staticmethod
    def sign_min_int(k):
        return -(2 ** (k - 1))


    @staticmethod
    def _ntz(x):
        '''
        Get the position of first non-zero bit
        :param x:
        :return:
        '''
        if x == 0:
            #FIXME: WTF?
            return 0

        y = (~x) & (x - 1)    # There is actually a bug in BAP until 0.8

        def bits(y):
            n = 0
            while y != 0:
                n += 1
                y >>= 1
            return n

        return bits(y)

    @staticmethod
    def _to_negative(a, bits):
        return -((1 << bits) - a)

    @staticmethod
    def upper(bits, i, stride):
        '''

        :return:
        '''
        if stride >= 1:
            offset = i % stride
            max = StridedInterval.max_int(bits)  # pylint:disable=redefined-builtin
            max_offset = max % stride

            if max_offset >= offset:
                o = max - (max_offset - offset)
            else:
                o = max - ((max_offset + stride) - offset)
            return o
        else:
            return StridedInterval.max_int(bits)

    @staticmethod
    def lower(bits, i, stride):
        '''

        :return:
        '''
        if stride >= 1:
            offset = i % stride
            min = StridedInterval.min_int(bits)  # pylint:disable=redefined-builtin
            min_offset = min % stride

            if offset >= min_offset:
                o = min + (offset - min_offset)
            else:
                o = min + ((offset + stride) - min_offset)
            return o
        else:
            return StridedInterval.min_int(bits)

    @staticmethod
    def _gap(src_interval, tar_interval):
        """
        Refer section 3.1; gap function
        :param src_interval: first argument or interval 1
        :param tar_interval: second argument or interval 2
        :return: Interval representing gap between two intervals
        """
        assert src_interval.bits == tar_interval.bits, "Number of bits should be same for operands"
        # use the same variable names as in paper
        s = src_interval
        t = tar_interval
        (a, b) = (s.lower_bound, s.upper_bound)
        (c, d) = (t.lower_bound, t.upper_bound)

        w = s.bits
        # case 1
        if (not t._wrapped_member(b)) and (not s._wrapped_member(c)):
            #FIXME: maybe we can do better here and to not fix the stride to 1
            return StridedInterval(lower_bound=c, upper_bound=b, bits=w, stride=1).complement
        # otherwise
        return StridedInterval.empty(w)

    @staticmethod
    def top(bits, name=None, uninitialized=False):
        '''
        Get a TOP StridedInterval

        :return:
        '''
        return StridedInterval(name=name,
                               bits=bits,
                               stride=1,
                               lower_bound=0,
                               upper_bound=StridedInterval.max_int(bits),
                               uninitialized=uninitialized)

    @staticmethod
    def empty(bits):
        return StridedInterval(bits=bits, bottom=True)

    @staticmethod
    def _wrapped_cardinality(x, y, bits):
        """
        Return the cardinality for a set of number (| x, y |) on the wrapped-interval domain
        :param x: The first operand (an integer)
        :param y: The second operand (an integer)
        :return: The cardinality
        """

        if x == ((y + 1) % (2 ** bits)):
            return 2 ** bits

        else:
            return ((y - x) + 1) & (2 ** bits - 1)

    @staticmethod
    def _is_msb_zero(v, bits):
        """
        Checks if the most significant bit is zero (i.e. is the integer positive under signed arithmetic)
        :param v: The integer to check with
        :param bits: Bits of the integer
        :return: True or False
        """
        return (v & (2 ** bits - 1)) & (2 ** (bits - 1)) == 0

    @staticmethod
    def _is_msb_one(v, bits):
        """
        Checks if the most significant bit is one (i.e. is the integer negative under signed arithmetic)
        :param v: The integer to check with
        :param bits: Bits of the integer
        :return: True or False
        """
        return not StridedInterval._is_msb_zero(v, bits)

    @staticmethod
    def _get_msb(v, bits):
        """
        Get the MSB (most significant bit)
        :param v: The integer
        :param bits: Bits of the integer
        :return: the MSB
        """
        if StridedInterval._is_msb_zero(v, bits):
            return 0
        return 1


    @staticmethod
    def _unsigned_to_signed(v, bits):
        """
        Convert an unsigned integer to a signed integer
        :param v: The unsigned integer
        :param bits: How many bits this integer should be
        :return: The converted signed integer
        """
        if StridedInterval._is_msb_zero(v, bits):
            return v
        else:
            return -(2 ** bits - v)

    @staticmethod
    def _wrappedoverflow_add(a, b):
        """
        Determines if an overflow happens during the addition of `a` and `b`.

        :param a: The first operand (StridedInterval)
        :param b: The other operand (StridedInterval)
        :return: True if overflows, False otherwise
        """

        if a.is_integer and a.lower_bound == 0:
            # Special case: if `a` or `b` is a zero
            card_self = 0
        else:
            card_self = StridedInterval._wrapped_cardinality(a.lower_bound, a.upper_bound, a.bits)

        if b.is_integer and b.lower_bound == 0:
            # Special case: if `a` or `b` is a zero
            card_b = 0
        else:
            card_b = StridedInterval._wrapped_cardinality(b.lower_bound, b.upper_bound, b.bits)

        return (card_self + card_b) > StridedInterval.max_int(a.bits)

    @staticmethod
    def _wrappedoverflow_sub(a, b):
        """
        Determines if an overflow happens during the subtraction of `a` and `b`.

        :param a: The first operand (StridedInterval)
        :param b: The other operand (StridedInterval)
        :return: True if overflows, False otherwise
        """

        return StridedInterval._wrappedoverflow_add(a, b)

    @staticmethod
    def _wrapped_unsigned_mul(a, b):
        """
        Perform wrapped unsigned multiplication on two StridedIntervals
        :param a: The first operand (StridedInterval)
        :param b: The second operand (StridedInterval)
        :return: The multiplication result
        """
        if a.bits != b.bits:
            logger.warning("Signed mul: two parameters have different bit length")

        bits = max(a.bits, b.bits)
        lb = a.lower_bound * b.lower_bound
        ub = a.upper_bound * b.upper_bound

        if (ub - lb) < (2 ** bits):
            if b.is_integer:
                # Multiplication with an integer, and it does not overflow!
                stride = abs(a.stride * b.lower_bound)
            elif a.is_integer:
                stride = abs(a.lower_bound * b.stride)
            else:
                stride = fractions.gcd(a.stride, b.stride)
            return StridedInterval(bits=bits, stride=stride, lower_bound=lb, upper_bound=ub)
        else:
            # Overflow occurred
            return StridedInterval.top(bits, uninitialized=False)


    @staticmethod
    def _wrapped_signed_mul(a, b):
        """
        Perform wrapped signed multiplication on two StridedIntervals
        :param a: The first operand (StridedInterval)
        :param b: The second operand (StridedInterval)
        :return: The product
        """

        #NOTE: interval here should never straddle poles
        #FIXME: add assert to be sure of it!

        if a.bits != b.bits:
            logger.warning("Signed mul: two parameters have different bit length")

        bits = max(a.bits, b.bits)

        # shorter SI
        a_lb_positive = StridedInterval._is_msb_zero(a.lower_bound, bits)
        a_ub_positive = StridedInterval._is_msb_zero(a.upper_bound, bits)
        b_lb_positive = StridedInterval._is_msb_zero(b.lower_bound, bits)
        b_ub_positive = StridedInterval._is_msb_zero(b.upper_bound, bits)

        if b.is_integer:
            # Multiplication with an integer, and it does not overflow!
            # Note that as long as it overflows, a TOP will be returned and the stride will be simply ignored
            stride = abs(a.stride * b.lower_bound)
        elif a.is_integer:
            stride = abs(a.lower_bound * b.stride)
        else:
            stride = fractions.gcd(a.stride, b.stride)

        if a_lb_positive and a_ub_positive and b_lb_positive and b_ub_positive:
            # [2, 5] * [10, 20] = [20, 100]
            lb = a.lower_bound * b.lower_bound
            ub = a.upper_bound * b.upper_bound

            if ub - lb < (2 ** bits):
                return StridedInterval(bits=bits, stride=stride, lower_bound=lb, upper_bound=ub)
            else:
                return StridedInterval.top(bits)

        elif not a_lb_positive and not a_ub_positive and not b_lb_positive and not b_ub_positive:
            # [-5, -2] * [-20, -10] = [20, 100]
            lb = (
                StridedInterval._unsigned_to_signed(a.upper_bound, bits) *
                StridedInterval._unsigned_to_signed(b.upper_bound, bits)
            )
            ub = (
                StridedInterval._unsigned_to_signed(a.lower_bound, bits) *
                StridedInterval._unsigned_to_signed(b.lower_bound, bits)
            )

            if ub - lb < (2 ** bits):
                return StridedInterval(bits=bits, stride=stride, lower_bound=lb, upper_bound=ub)
            else:
                return StridedInterval.top(bits)

        elif not a_lb_positive and not a_ub_positive and b_lb_positive and b_ub_positive:
            # [-10, -2] * [2, 5] = [-50, -4]
            lb = StridedInterval._unsigned_to_signed(a.lower_bound, bits) * b.upper_bound
            ub = StridedInterval._unsigned_to_signed(a.upper_bound, bits) * b.lower_bound
            # since the intervals do not straddle the poles, ub is greater than lb
            if ub - lb < (2 ** bits):
                lb &= (2 ** bits - 1)
                ub &= (2 ** bits - 1)
                return StridedInterval(bits=bits, stride=stride, lower_bound=lb, upper_bound=ub)
            else:
                return StridedInterval.top(bits)

        elif a_lb_positive and a_ub_positive and not b_lb_positive and not b_ub_positive:
            # [2, 10] * [-5, -2] = [-50, -4]
            lb = a.upper_bound * StridedInterval._unsigned_to_signed(b.lower_bound, bits)
            ub = a.lower_bound * StridedInterval._unsigned_to_signed(b.upper_bound, bits)
            # since the intervals do not straddle the poles, ub is greater than lb
            if ub - lb < (2 ** bits):
                lb &= (2 ** bits - 1)
                ub &= (2 ** bits - 1)
                return StridedInterval(bits=bits, stride=stride, lower_bound=lb, upper_bound=ub)
            else:
                return StridedInterval.top(bits)

        else:
            raise Exception('We shouldn\'t see this case: %s * %s' % (a, b))

    @staticmethod
    def _wrapped_unsigned_div(a, b):
        """
        Perform wrapped unsigned division on two StridedIntervals.

        :param a: The dividend (StridedInterval)
        :param b: The divisor (StridedInterval)
        :return: The quotient
        """

        bits = max(a.bits, b.bits)

        divisor_lb, divisor_ub = b.lower_bound, b.upper_bound

        # Make sure divisor_lb and divisor_ub is not 0
        if divisor_lb == 0:
            # Can we increment it?
            if divisor_ub == 0:
                # We can't :-(
                return StridedInterval.empty(bits)
            else:
                divisor_lb += 1
        # If divisor_ub is 0, decrement it to get last but one element
        if divisor_ub == 0:
            divisor_ub = (divisor_ub - 1) & (2 ** bits - 1)

        lb = a.lower_bound / divisor_ub
        ub = a.upper_bound / divisor_lb

        # TODO: Can we make a more precise estimate of the stride?
        stride = 1

        return StridedInterval(bits=bits, stride=stride, lower_bound=lb, upper_bound=ub)

    @staticmethod
    def _wrapped_signed_div(a, b):
        """
        Perform wrapped unsigned division on two StridedIntervals.

        :param a: The dividend (StridedInterval)
        :param b: The divisor (StridedInterval)
        :return: The quotient
        """

        bits = max(a.bits, b.bits)

        # Make sure the divisor is not 0
        divisor_lb = b.lower_bound
        divisor_ub = b.upper_bound
        if divisor_lb == 0:
            # Try to increment it
            if divisor_ub == 0:
                return StridedInterval.empty(bits)
            else:
                divisor_lb = 1
        # If divisor_ub is 0, decrement it to get last but one element
        if divisor_ub == 0:
            divisor_ub = (divisor_ub - 1) & (2 ** bits - 1)

        dividend_positive = StridedInterval._is_msb_zero(a.lower_bound, bits)
        divisor_positive = StridedInterval._is_msb_zero(b.lower_bound, bits)

        # TODO: Can we make a more precise estimate of the stride?
        stride = 1
        if dividend_positive and divisor_positive:
            # They are all positive numbers!
            lb = a.lower_bound / divisor_ub
            ub = a.upper_bound / divisor_lb

        elif dividend_positive and not divisor_positive:
            # + / -
            lb = a.upper_bound / StridedInterval._unsigned_to_signed(divisor_ub, bits)
            ub = a.lower_bound / StridedInterval._unsigned_to_signed(divisor_lb, bits)

        elif not dividend_positive and divisor_positive:
            # - / +
            lb = StridedInterval._unsigned_to_signed(a.lower_bound, bits) / divisor_lb
            ub = StridedInterval._unsigned_to_signed(a.upper_bound, bits) / divisor_ub

        else:
            # - / -
            lb = StridedInterval._unsigned_to_signed(a.upper_bound, bits) / \
                 StridedInterval._unsigned_to_signed(b.lower_bound, bits)
            ub = StridedInterval._unsigned_to_signed(a.lower_bound, bits) / \
                 StridedInterval._unsigned_to_signed(b.upper_bound, bits)

        return StridedInterval(bits=bits, stride=stride, lower_bound=lb, upper_bound=ub)

    #
    # Membership testing and poset ordering
    #

    @staticmethod
    def _lex_lte(x, y, bits):
        """
        Lexicographical LTE comparison

        :param x: The first operand (integer)
        :param y: The second operand (integer)
        :param bits: bit-width of the operands
        :return: True or False
        """

        return (x & (2 ** bits - 1)) <= (y & (2 ** bits - 1))

    @staticmethod
    def _lex_lt(x, y, bits):
        """
        Lexicographical LT comparison

        :param x: The first operand (integer)
        :param y: The second operand (integer)
        :param bits: bit-width of the operands
        :return: True or False
        """

        return (x & (2 ** bits - 1)) < (y & (2 ** bits - 1))

    def _wrapped_member(self, v):
        """
        Test if integer v belongs to StridedInterval a

        :param self: A StridedInterval instance
        :param v: An integer
        :return: True or False
        """

        a = self
        return self._lex_lte(v - a.lower_bound, a.upper_bound - a.lower_bound, a.bits)

    def _wrapped_lte(self, b):
        """
        Perform a wrapped LTE comparison based on the poset ordering

        :param a: The first operand
        :param b: The second operand
        :return: True if a <= b, False otherwise
        """

        a = self
        if a.is_empty:
            return True

        if a.is_top and b.is_top:
            return True

        elif a.is_top:
            return False

        elif b.is_top:
            return True

        if b._wrapped_member(a.lower_bound) and b._wrapped_member(a.upper_bound):
            if ((b.lower_bound == a.lower_bound and b.upper_bound == a.upper_bound)
                    or not a._wrapped_member(b.lower_bound) or not a._wrapped_member(b.upper_bound)):
                return True
        return False

    #
    # Arithmetic operations
    #

    @reversed_processor
    def neg(self):
        """
        Unary operation: neg

        :return: 0 - self
        """

        return StridedInterval(bits=self.bits, stride=0, lower_bound=0, upper_bound=0).sub(self)

    @normalize_types
    def add(self, b):
        """
        Binary operation: add

        :param b: The other operand
        :return: self + b
        """
        new_bits = max(self.bits, b.bits)

        # TODO: Some improvements can be made here regarding the following case
        # TODO: SI<16>0xff[0x0, 0xff] + 3
        # TODO: In current implementation, it overflows, but it doesn't have to

        overflow = self._wrappedoverflow_add(self, b)
        if overflow:
            return StridedInterval.top(self.bits)

        lb = self._modular_add(self.lower_bound, b.lower_bound, new_bits)
        ub = self._modular_add(self.upper_bound, b.upper_bound, new_bits)

        # Is it initialized?
        uninitialized = self.uninitialized or b.uninitialized

        # Take the GCD of two operands' strides
        stride = fractions.gcd(self.stride, b.stride)

        return StridedInterval(bits=new_bits, stride=stride, lower_bound=lb, upper_bound=ub,
                               uninitialized=uninitialized).normalize()

    @normalize_types
    def sub(self, b):
        """
        Binary operation: sub

        :param b: The other operand
        :return: self - b
        """
        new_bits = max(self.bits, b.bits)

        overflow = self._wrappedoverflow_sub(self, b)
        if overflow:
            return StridedInterval.top(self.bits)

        lb = self._modular_sub(self.lower_bound, b.upper_bound, new_bits)
        ub = self._modular_sub(self.upper_bound, b.lower_bound, new_bits)

        # Is it initialized?
        uninitialized = self.uninitialized or b.uninitialized

        # Take the GCD of two operands' strides
        stride = fractions.gcd(self.stride, b.stride)

        return StridedInterval(bits=new_bits, stride=stride, lower_bound=lb, upper_bound=ub,
                               uninitialized=uninitialized).normalize()

    @normalize_types
    def mul(self, o):
        """
        Binary operation: multiplication

        :param o: The other operand
        :return: self * o
        """

        if self.is_integer and o.is_integer:
            # Two integers!
            a, b = self.lower_bound, o.lower_bound
            ret = StridedInterval(bits=self.bits,
                                  stride=0,
                                  lower_bound=a * b,
                                  upper_bound=a * b
                                  )

            if a * b > (2 ** self.bits - 1):
                logger.warning('Overflow in multiplication detected.')

            return ret.normalize()

        else:
            # All other cases

            # Cut from both north pole and south pole
            si1_psplit = self._psplit()
            si2_psplit = o._psplit()
            all_resulting_intervals = list()

            for si1 in si1_psplit:
                for si2 in si2_psplit:
                    tmp_unsigned_mul = self._wrapped_unsigned_mul(si1, si2)
                    tmp_signed_mul = self._wrapped_signed_mul(si1, si2)
                    for tmp_meet in tmp_unsigned_mul.intersection(tmp_signed_mul):
                        all_resulting_intervals.append(tmp_meet)

        return StridedInterval._least_upper_bound(list(all_resulting_intervals)).normalize()

    @normalize_types
    def sdiv(self, o):
        """
        Binary operation: signed division

        :param o: The divisor
        :return: (self / o) in signed arithmetic
        """

        splitted_dividends = self._psplit()
        splitted_divisors = o._psplit()

        ret = self.empty(self.bits)
        resulting_intervals = set()
        for dividend in splitted_dividends:
            for divisor in splitted_divisors:
                tmp = self._wrapped_signed_div(dividend, divisor)
                resulting_intervals.add(tmp)

        return StridedInterval._least_upper_bound(list(resulting_intervals)).normalize()

    @normalize_types
    def udiv(self, o):
        """
        Binary operation: unsigned division

        :param o: The divisor
        :return: (self / o) in unsigned arithmetic
        """

        splitted_dividends = self._ssplit()
        splitted_divisors = o._ssplit()

        ret = self.empty(self.bits)
        resulting_intervals = set()
        for dividend in splitted_dividends:
            for divisor in splitted_divisors:
                tmp = self._wrapped_unsigned_div(dividend, divisor)
                resulting_intervals.add(tmp)

        return StridedInterval._least_upper_bound(list(resulting_intervals)).normalize()

    @reversed_processor
    def bitwise_not(self):
        """
        Unary operation: bitwise not

        :return: ~self
        """
        splitted_si = self._ssplit()
        if len(splitted_si) == 0:
            return StridedInterval.empty(self.bits)

        result_interval = list()
        for si in splitted_si:
            lb = ~si.upper_bound
            ub = ~si.lower_bound
            stride = self.stride

            tmp = StridedInterval(bits=self.bits, stride=stride, lower_bound=lb, upper_bound=ub)
            result_interval.append(tmp)
        return StridedInterval._least_upper_bound(list(result_interval)).normalize()

    @normalize_types
    def bitwise_or(self, t):
        """
        Binary operation: logical or
        :param b: The other operand
        :return: self | b
        """

        #FIXME: implement the stride. refer to WYSINWYX What You See Is Not What You eXecute section 4.2.4
        # Using same variables as in paper
        s = self
        result_interval = list()
        new_stride = 1
        for u in s._ssplit():
            for v in t._ssplit():
                w = u.bits
                # u |w v
                low_bound = WarrenMethods.min_or(u.lower_bound, u.upper_bound, v.lower_bound, v.upper_bound, w)
                upper_bound = WarrenMethods.max_or(u.lower_bound, u.upper_bound, v.lower_bound, v.upper_bound, w)
                new_interval = StridedInterval(lower_bound=low_bound, upper_bound=upper_bound, bits=w, stride=new_stride)
                result_interval.append(new_interval)
        return StridedInterval._least_upper_bound(result_interval).normalize()

    @normalize_types
    def bitwise_and(self, t):
        """
        Binary operation: logical and
        :param b: The other operand
        :return:
        """

        #FIXME: implement the stride. refer to WYSINWYX What You See Is Not What You eXecute section 4.2.5
        # Using same variables as in paper
        s = self
        result_interval = list()
        new_stride = 1
        for u in s._ssplit():
            for v in t._ssplit():
                w = u.bits
                # u &w v
                low_bound = WarrenMethods.min_and(u.lower_bound, u.upper_bound, v.lower_bound, v.upper_bound, w)
                upper_bound = WarrenMethods.max_and(u.lower_bound, u.upper_bound, v.lower_bound, v.upper_bound, w)
                new_interval = StridedInterval(lower_bound=low_bound, upper_bound=upper_bound, bits=w, stride=new_stride)
                result_interval.append(new_interval)
        return StridedInterval._least_upper_bound(list(result_interval)).normalize()

    @normalize_types
    def bitwise_xor(self, t):
        '''
        Operation xor
        :param b: The other operand
        :return:
        '''

        #FIXME: implement the stride. refer to WYSINWYX What You See Is Not What You eXecute section 4.2.5
        # Using same variables as in paper
        s = self
        result_interval = list()
        new_stride = 1
        for u in s._ssplit():
            for v in t._ssplit():
                w = u.bits
                # u |w v
                low_bound = WarrenMethods.min_xor(u.lower_bound, u.upper_bound, v.lower_bound, v.upper_bound, w)
                upper_bound = WarrenMethods.max_xor(u.lower_bound, u.upper_bound, v.lower_bound, v.upper_bound, w)
                new_interval = StridedInterval(lower_bound=low_bound, upper_bound=upper_bound, bits=w, stride=mew_stride)
                result_interval.append(new_interval)
        return StridedInterval._least_upper_bound(list(result_interval)).normalize()


    def _pre_shift(self, shift_amount):
        def get_range(expr):
            '''
            Get the range of bits for shifting
            :param expr:
            :return: A tuple of maximum and minimum bits to shift
            '''
            def round(max, x): #pylint:disable=redefined-builtin
                if x < 0 or x > max:
                    return max
                else:
                    return x

            if type(expr) in [int, long]:
                return (expr, expr)

            assert type(expr) is StridedInterval

            if expr.is_integer:
                return (round(self.bits, expr.lower_bound),
                        round(self.bits, expr.lower_bound))
            else:
                if expr.lower_bound < 0:
                    if expr.upper_bound >= 0:
                        return (0, self.bits)
                    else:
                        return (self.bits, self.bits)
                else:
                    return (round(self.bits, self.lower_bound), round(self.bits, self.upper_bound))

        lower, upper = get_range(shift_amount)
        # TODO: Is trancating necessary?

        return lower, upper

    @reversed_processor
    def rshift(self, shift_amount, preserve_sign=False):
        lower, upper = self._pre_shift(shift_amount)

        # Shift the lower_bound and upper_bound by all possible amounts, and
        # get min/max values from all the resulting values

        new_lower_bound = None
        new_upper_bound = None
        lower_bound_shifted = 0
        upper_bound_shifted = 0
        for shift_amount in xrange(lower, upper + 1):
            l = self.lower_bound >> shift_amount
            if new_lower_bound is None or l < new_lower_bound:
                new_lower_bound = l
                lower_bound_shifted = shift_amount
            u = self.upper_bound >> shift_amount
            if new_upper_bound is None or u > new_upper_bound:
                new_upper_bound = u
                upper_bound_shifted = shift_amount

        # NOTE: If this is an arithmetic operation, we should take care
        # of sign-changes.
        if preserve_sign:
            mask = (2 ** (self.bits - 1))
            if (self.lower_bound & mask) > 0:
                bits_sign = ((2 ** lower_bound_shifted) - 1) << (self.bits - lower_bound_shifted)
                new_lower_bound |= bits_sign

            if (self.upper_bound & mask) > 0:
                bits_sign = ((2 ** upper_bound_shifted) - 1) << (self.bits - upper_bound_shifted)
                new_upper_bound |= bits_sign

        ret = StridedInterval(bits=self.bits,
                               stride=max(self.stride >> upper, 1),
                               lower_bound=new_lower_bound,
                               upper_bound=new_upper_bound)
        ret.normalize()

        return ret

    @reversed_processor
    def lshift(self, shift_amount):
        lower, upper = self._pre_shift(shift_amount)

        # Shift the lower_bound and upper_bound by all possible amounts, and
        # get min/max values from all the resulting values

        new_lower_bound = None
        new_upper_bound = None
        for shift_amount in xrange(lower, upper + 1):
            l = self.lower_bound << shift_amount
            if new_lower_bound is None or l < new_lower_bound:
                new_lower_bound = l
            u = self.upper_bound << shift_amount
            if new_upper_bound is None or u > new_upper_bound:
                new_upper_bound = u

        # NOTE: If this is an arithmetic operation, we should take care
        # of sign-changes.

        ret = StridedInterval(bits=self.bits,
                               stride=max(self.stride << lower, 1),
                               lower_bound=new_lower_bound,
                               upper_bound=new_upper_bound)
        ret.normalize()

        return ret

    @reversed_processor
    def cast_low(self, tok):
        assert tok <= self.bits

        mask = (1 << tok) - 1

        if self.stride >= (1 << tok):
            #this should be bottom
            logger.warning('Tried to cast_low an interval to a an interval shorter than its stride.')
            if self.lower_bound & mask == self.lower_bound:
                return StridedInterval(bits=tok, stride=0,
                                       lower_bound=self.lower_bound,
                                       upper_bound=self.lower_bound)
            StridedInterval.empty(tok)

        if tok == self.bits:
            return self.copy()
        else:
            # the interval can be represented in tok bits
            if (self.lower_bound & mask) == self.lower_bound and \
                (self.upper_bound & mask) == self.upper_bound:
                return StridedInterval(bits=tok, stride=self.stride,
                                       lower_bound=self.lower_bound,
                                       upper_bound=self.upper_bound)

            # the range between lower bound and upper bound can be represented
            # in the new SI
            elif self.upper_bound - self.lower_bound <= mask:
                l = self.lower_bound & mask
                u = self.upper_bound & mask
                # Keep the signs!
                if self.lower_bound < 0:
                    # how this should happen ?
                    import ipdb; ipdb.set_trace()
                    l = StridedInterval._to_negative(l, tok)
                if self.upper_bound < 0:
                    # how this should happen ?
                    import ipdb; ipdb.set_trace()
                    u = StridedInterval._to_negative(u, tok)
                return StridedInterval(bits=tok, stride=self.stride,
                                       lower_bound=l,
                                       upper_bound=u)

            elif (self.upper_bound & mask == self.lower_bound & mask) and \
                ((self.upper_bound - self.lower_bound) & mask == 0):
                # This operation doesn't affect the stride. Stride should be 0 then.

                bound = self.lower_bound & mask

                return StridedInterval(bits=tok,
                                       stride=0,
                                       lower_bound=bound,
                                       upper_bound=bound)

            else:
                # TODO: How can we do better here? For example, keep the stride information?
                return self.top(tok)

    @normalize_types
    def concat(self, b):

        # Zero-extend
        a = self.nameless_copy()
        a._bits += b.bits

        new_si = a.lshift(b.bits)
        new_b = b.copy()
        # Zero-extend b
        new_b._bits = new_si.bits

        if new_si.is_integer:
            # We can be more precise!
            new_si._bits = new_b.bits
            new_si._stride = new_b.stride
            new_si._lower_bound = new_si.lower_bound + b.lower_bound
            new_si._upper_bound = new_si.upper_bound + b.upper_bound
            return new_si
        else:
            return new_si.bitwise_or(new_b)

    @reversed_processor
    def extract(self, high_bit, low_bit):

        assert low_bit >= 0

        bits = high_bit - low_bit + 1

        if low_bit != 0:
            ret = self.rshift(low_bit)
        else:
            ret = self.copy()
        if bits != self.bits:
            ret = ret.cast_low(bits)

        return ret.normalize()

    @reversed_processor
    def agnostic_extend(self, new_length):
        """
        Unary operation: SignExtend

        :param new_length: New length after sign-extension
        :return: A new StridedInterval
        """
        '''
        In a sign-agnostic implementation of strided-intervals a number can be signed or unsigned both.
        Given a SI, we must pay attention how we extend its lower bound and upper bound.
        Assuming that the lower bound is in the left emishpere (positive number).
        Let's assume first that the SI is signed and its upper bound is in the right emisphere. Extending it with leading
        1s (i.e., its MSB)  is correct given that its values would be preserved.
        On the other hand if the number is unsigned we should not replicate its MSB, since this would increase the value
        of the upper bound in the new interval. In this case the correct approach would be to add 0 in front of the number,
        i.e., moving it to the left emisphere. But this approach wouldn't be correct in the first scenario (signed SI).
        The solution in this case is extend the upper bound with 1s. This gives us an overapproximation of the original
        SI.

        Extending this intuition, the implementation follows the below rules:
        (UB: upper bound, LB: lower bound, RE: right emisphere, LE: left emisphere)
        1* UB:LE and LB:LE: add leading 0s (sound and precise).
        2* UB:RE and LB:RE and the LB is closer to the north pole: add leading 0s to LB and leading 1s to the UB (sound)
        3* UB:RE and LB:RE and UB is closer to the north pole: add leading 1s to LB and UB both (sound).
        4* UB:LE and LB:RE: add leading 0s to UB and leading 0s to LB (sound).
        5* UB:RE and LB:LE: add leading 0s to LB and leading 1s to UB (sound).
        6* UB:RE and LB:RE and LB = UB: add leading 1s to LB and UB both
        '''

        si = self.copy()
        si._bits = new_length

        leading_1_lb = False
        leading_1_ub = False

        ub_msb = self._get_msb(self.upper_bound, self.bits)
        lb_msb = self._get_msb(self.lower_bound, self.bits)

        # LB:RE cases
        if lb_msb == 1:
            #2
            if ub_msb == 1 and self.upper_bound > self.lower_bound:
                leading_1_ub = True
            #3/#6
            if ub_msb == 1 and self.lower_bound >= self.upper_bound:
                leading_1_ub = True
                leading_1_lb = True
        #5
        elif ub_msb == 1:
          leading_1_ub = True

        if leading_1_lb:
            mask = (2 ** new_length - 1) - (2 ** self.bits - 1)
            si._lower_bound |= mask
        if leading_1_ub:
            mask = (2 ** new_length - 1) - (2 ** self.bits - 1)
            si._upper_bound |= mask

        return si

    @reversed_processor
    def zero_extend(self, new_length):
        """
        Unary operation: ZeroExtend

        :param new_length: New length after zero-extension
        :return: A new StridedInterval
        """
        si = self.copy()
        si._bits = new_length

        return si

    @normalize_types
    def _interval_extend(self, t):
        """
        Extend src interval to include destination
        Refer 1:11 of paper:
        Interval analysis and machine arithmetic: Why signedness ignorance is bliss
        :param src_interval: Interval to extend
        :param dst_interval: Interval to be extended to
        :return: Interval starting from src interval which also includes dst interval
        """
        s = self
        w = s.bits
        (a, b) = (s.lower_bound, s.upper_bound)
        (c, d) = (t.lower_bound, t.upper_bound)

        # case 1: s <= t
        if s._wrapped_lte(t):
            return t.copy()
        # case 2: t <= s
        if t._wrapped_lte(s):
            return s.copy()
        # case 3: neg(s) <= t
        if s.complement._wrapped_lte(t):
            return StridedInterval.top(w)

        # otherwise
        # this is a bit tricky. In extending a SI with another, we must assure that every numbers
        # represented by both intervals are represented by the new one. This property is assured if we use
        # as new stride the GCD of the two old strides AND if we assure that the lower bound of the SI 't' is
        # present among the values when the new SI is evaluated.
        if s.is_integer and t.is_integer:
            new_stride = StridedInterval._wrapped_cardinality(a, c, w) - 1
        elif s.is_integer:
            new_stride = fractions.gcd(StridedInterval._wrapped_cardinality(a, c, w) - 1, t._stride)
        elif t.is_integer:
            new_stride = fractions.gcd(StridedInterval._wrapped_cardinality(b, c, w) - 1, s._stride)
        else:
            new_stride = fractions.gcd(s._stride, t._stride)
            new_stride = fractions.gcd(new_stride, StridedInterval._wrapped_cardinality(a, c, w) - 1)

        # this happens when s and t are the same integer
        if new_stride == -1:
            new_stride = 0

        return StridedInterval(lower_bound=a, upper_bound=d, bits=w, stride=new_stride)

    @reversed_processor
    def sign_extend(self, new_length):
        """
        Unary operation: SignExtend

        :param new_length: New length after sign-extension
        :return: A new StridedInterval
        """

        msb = self.extract(self.bits - 1, self.bits - 1).eval(2)
        if msb == [ 0 ]:
            # All positive numbers
            return self.zero_extend(new_length)
        if msb == [ 1 ]:
            # All negative numbers
            si = self.copy()
            si._bits = new_length
            mask = (2 ** new_length - 1) - (2 ** self.bits - 1)
            si._lower_bound = si._lower_bound | mask
            si._upper_bound = si._upper_bound | mask

        else:
            # Both positive numbers and negative numbers
            numbers = self._nsplit()
            # Since there are both positive and negative numbers, there must be two bounds after nsplit
            # assert len(numbers) == 2
            si = self.empty(new_length)
            for n in numbers:
                a, b = n.lower_bound, n.upper_bound
                if b < 2 ** (n.bits - 1):
                    # msb = 0
                    si_ = StridedInterval(bits=new_length, stride=n.stride, lower_bound=a, upper_bound=b)
                else:
                    # msb = 1
                    mask = (2 ** new_length - 1) - (2 ** self.bits - 1)
                    si_ = StridedInterval(bits=new_length, stride=n.stride, lower_bound=a | mask, upper_bound=b | mask)
                si = si.union(si_)
        return si

    @normalize_types
    def union(self, b):
        """
        The union operation. It might return a DiscreteStridedIntervalSet to allow for better precision in analysis.

        :param b: Operand
        :return: A new DiscreteStridedIntervalSet, or a new StridedInterval.
        """
        if not allow_dsis:
            return StridedInterval._least_upper_bound([self, b])

        else:
            if self.cardinality > discrete_strided_interval_set.MAX_CARDINALITY_WITHOUT_COLLAPSING or \
                    b.cardinality > discrete_strided_interval_set:
                return StridedInterval._least_upper_bound([self, b])

            else:
                dsis = DiscreteStridedIntervalSet(bits=self._bits, si_set={ self })
                return dsis.union(b)

    @staticmethod
    def _bigger(interval1, interval2):
        """
        Return interval with bigger cardinality
        Refer Section 3.1
        :param interval1: first interval
        :param interval2: second interval
        :return: Interval or interval2 whichever has greater cardinality
        """
        if interval2.cardinality > interval1.cardinality:
            return interval2.copy()
        return interval1.copy()


    @staticmethod
    def _least_upper_bound(intervals_to_join):
        """
        Pseudo least upper bound.
        Join the given set of intervals into a big interval
        Refer section 3.1
        :param intervals_to_join: Intervals to join
        :return: Interval that contains all intervals
        """

        assert len(intervals_to_join) > 0, "No intervals to join"
        # Optimization: If we have only one interval, then return that interval as result
        if len(intervals_to_join) == 1:
            return intervals_to_join[0].copy()
        # Check if all intervals are of same width
        all_same = all(x.bits == intervals_to_join[0].bits for x in intervals_to_join)
        assert all_same, "All intervals to join should be same"
        # sort the intervals in increasing left bound
        sorted_intervals = sorted(intervals_to_join, key=lambda x: x.lower_bound)
        # Fig 3 of the paper
        w = intervals_to_join[0].bits
        f = StridedInterval.empty(w)
        g = StridedInterval.empty(w)
        for s in sorted_intervals:
            if s.is_top or StridedInterval._lex_lte(s.upper_bound, s.lower_bound, w):
                # f <- extend(f, s)
                f = f._interval_extend(s)
        for s in sorted_intervals:
            # g <- bigger(g, gap(f, s))
            g = StridedInterval._bigger(g, StridedInterval._gap(f, s))
            # f <- extend(f, s)
            f = f._interval_extend(s)

        si = StridedInterval._bigger(g, f.complement).complement

        # stride
        if si.is_integer:
            si._stride = 0
        if si.is_top:
            si._stride = 1
        else:
            stride = intervals_to_join[0]._stride
            for i in intervals_to_join:
                stride = fractions.gcd(stride, i._stride)
            si._stride = stride

        return si


    @normalize_types
    def _union(self, b):
        """
        Binary operation: union
        It's also the join operation.

        :param b: The other operand.
        :return: A new StridedInterval
        """

        logger.warning("StridedInterval._union will be deprecated soon. Please use StridedInterval._least_upper_bound instead.")

        if self._reversed != b._reversed:
            logger.warning('Incoherent reversed flag between operands %s and %s', self, b)

        #
        # Trivial cases
        #

        if self.is_empty:
            return b
        if b.is_empty:
            return self

        if self.is_integer and b.is_integer:
            u = max(self.upper_bound, b.upper_bound)
            l = min(self.lower_bound, b.lower_bound)
            stride = abs(u - l)
            return StridedInterval(bits=self.bits, stride=stride, lower_bound=l, upper_bound=u)

        #
        # Other cases
        #

        # Determine the new stride
        if self.is_integer:
            new_stride = fractions.gcd(self._modular_sub(self.lower_bound, b.lower_bound, self.bits), b.stride)
        elif b.is_integer:
            new_stride = fractions.gcd(self.stride, self._modular_sub(b.lower_bound, self.lower_bound, self.bits))
        else:
            new_stride = fractions.gcd(self.stride, b.stride)

        remainder_1 = self.lower_bound % new_stride if new_stride > 0 else 0
        remainder_2 = b.lower_bound % new_stride if new_stride > 0 else 0
        if remainder_1 != remainder_2:
            new_stride = fractions.gcd(abs(remainder_1 - remainder_2), new_stride)

        # Then we have different cases

        if self._wrapped_lte(b):
            # Containment

            return StridedInterval(bits=self.bits, stride=new_stride, lower_bound=b.lower_bound,
                                   upper_bound=b.upper_bound)

        elif b._wrapped_lte(self):
            # Containment

            # TODO: This case is missing in the original implementation. Is that a bug?
            return StridedInterval(bits=self.bits, stride=new_stride, lower_bound=self.lower_bound,
                                   upper_bound=self.upper_bound)

        elif (self._wrapped_member(b.lower_bound) and self._wrapped_member(b.upper_bound) and
            b._wrapped_member(self.lower_bound) and b._wrapped_member(self.upper_bound)):
            # The union of them covers the entire sphere

            return StridedInterval.top(self.bits)

        elif self._wrapped_member(b.lower_bound):
            # Overlapping

            return StridedInterval(bits=self.bits, stride=new_stride, lower_bound=self.lower_bound,
                                   upper_bound=b.upper_bound)

        elif b._wrapped_member(self.lower_bound):
            # Overlapping

            return StridedInterval(bits=self.bits, stride=new_stride, lower_bound=b.lower_bound,
                                   upper_bound=self.upper_bound)

        else:
            card_1 = self._wrapped_cardinality(self.upper_bound, b.lower_bound, self.bits)
            card_2 = self._wrapped_cardinality(b.upper_bound, self.lower_bound, self.bits)

            if card_1 == card_2:
                # Left/right leaning cases
                if self._lex_lt(self.lower_bound, b.lower_bound, self.bits):
                    return StridedInterval(bits=self.bits, stride=new_stride, lower_bound=self.lower_bound,
                                           upper_bound=b.upper_bound)

                else:
                    return StridedInterval(bits=self.bits, stride=new_stride, lower_bound=b.lower_bound,
                                           upper_bound=self.upper_bound)

            elif card_1 < card_2:
                # non-overlapping case (left)
                return StridedInterval(bits=self.bits, stride=new_stride, lower_bound=self.lower_bound,
                                       upper_bound=b.upper_bound)

            else:
                # non-overlapping case (right)
                return StridedInterval(bits=self.bits, stride=new_stride, lower_bound=b.lower_bound,
                                       upper_bound=self.upper_bound)

    @normalize_types
    def intersection(self, t):
        s = self
        w = s.bits
        if s.is_empty or t.is_empty:
            return { StridedInterval.empty(w) }

        assert s.bits == t.bits
        if s.is_integer and t.is_integer:
            if s.lower_bound == t.lower_bound:
                # They are the same number!
                return { StridedInterval(bits=w,
                                      stride=0,
                                      lower_bound=s.lower_bound,
                                      upper_bound=s.lower_bound) }
            else:
                return { StridedInterval.empty(w) }

        elif s.is_integer:
            integer = s.lower_bound
            if (t.lower_bound - integer) % t.stride == 0 and \
                    t._wrapped_member(integer):
                return { StridedInterval(bits=w,
                                      stride=0,
                                      lower_bound=integer,
                                      upper_bound=integer) }
            else:
                return { StridedInterval.empty(w) }

        elif t.is_integer:
            integer = t.lower_bound
            if (integer - s.lower_bound) % s.stride == 0 and \
                    s._wrapped_member(integer):
                return { StridedInterval(bits=w,
                                      stride=0,
                                      lower_bound=integer,
                                      upper_bound=integer) }
            else:
                return { StridedInterval.empty(w) }

        else:
            # None of the operands is an integer

            #FIXME: Fish used LCM, I think we should use GCD
            #new_stride = s.lcm(s.stride, t.stride)
            # example mcm doesn't work: s = 3[1, 10], t = 2[2, 8]
            new_stride = fractions.gcd(s._stride, t._stride)

            # case 1
            if s.is_bottom or t.is_bottom:
                return { StridedInterval.empty(w) }
            # case 2
            # s == t
            if (s.lower_bound == t.lower_bound and s.upper_bound == t.upper_bound) or s.is_top:
                item = t.copy()
                item._stride = new_stride
                return { item }
            # case 3
            if t.is_top:
                return { s.copy() }

            (a, b) = (s.lower_bound, s.upper_bound)
            (c, d) = (t.lower_bound, t.upper_bound)
            # case 4
            if t._wrapped_member(a) and t._wrapped_member(b) and s._wrapped_member(c) and s._wrapped_member(d):
                item1 = StridedInterval(lower_bound=a, upper_bound=d, bits=w, stride=new_stride)
                item2 = StridedInterval(lower_bound=c, upper_bound=b, bits=w, stride=new_stride)
                return { item1, item2 }
            # case 5
            if t._wrapped_member(a) and t._wrapped_member(b):
                item = s.copy()
                item._stride = new_stride
                return { item }
            # case 6
            if s._wrapped_member(c) and s._wrapped_member(d):
                item = t.copy()
                item._stride = new_stride
                return { item }
            # case 7
            if t._wrapped_member(a) and s._wrapped_member(d) and (not t._wrapped_member(b)) and (not s._wrapped_member(c)):
                item1 = StridedInterval(lower_bound=a, upper_bound=d, bits=w, stride=new_stride)
                return { item1 }
            # case 8
            if t._wrapped_member(b) and s._wrapped_member(c) and (not t._wrapped_member(a)) and (not s._wrapped_member(d)):
                item1 = StridedInterval(lower_bound=c, upper_bound=b, bits=w, stride=new_stride)
                return { item1 }
        # otherwise
        return { StridedInterval.empty(w) }

    @normalize_types
    def widen(self, b):
        ret = None

        if self.is_empty and not b.is_empty:
            ret = StridedInterval.top(bits=self.bits)

        elif self.is_empty:
            ret = b

        elif b.is_empty:
            ret = self

        else:
            new_stride = fractions.gcd(self.stride, b.stride)
            l = StridedInterval.lower(self.bits, self.lower_bound, new_stride) if b.lower_bound < self.lower_bound else self.lower_bound
            u = StridedInterval.upper(self.bits, self.upper_bound, new_stride) if b.upper_bound > self.upper_bound else self.upper_bound
            if new_stride == 0:
                if self.is_integer and b.is_integer:
                    ret = StridedInterval(bits=self.bits, stride=1, lower_bound=l, upper_bound=u)
                else:
                    raise ClaripyOperationError('SI: operands are not reduced.')
            else:
                ret = StridedInterval(bits=self.bits, stride=new_stride, lower_bound=l, upper_bound=u)

        ret.normalize()
        return ret

    def reverse(self):
        """
        This is a delayed reversing function. All it really does is to invert the _reversed property of this
        StridedInterval object.

        :return: None
        """
        if self.bits == 8:
            # We cannot reverse a one-byte value
            return self.copy()

        si = self.copy()
        si._reversed = not si._reversed

        return si

    def _reverse(self):
        """
        This method reverses the StridedInterval object for real. Do expect loss of precision for most cases!

        :return: A new reversed StridedInterval instance
        """

        o = self.copy()
        # Clear the reversed flag
        o._reversed = not o._reversed

        if o.bits == 8:
            # No need for reversing
            return o.copy()

        if o.is_top:
            # A TOP is still a TOP after reversing
            si = o.copy()
            return si

        else:
            if not o.is_integer:
                # We really don't want to do that... but well, sometimes it just happens...
                logger.warning('Reversing a real strided-interval %s is bad', self)

            # Reversing an integer is easy
            rounded_bits = ((o.bits + 7) / 8) * 8
            list_bytes = [ ]
            si = None

            for i in xrange(0, rounded_bits, 8):
                b = o.extract(min(i + 7, o.bits - 1), i)
                list_bytes.append(b)

            for b in list_bytes:
                si = b if si is None else si.concat(b)

            return si

def CreateStridedInterval(name=None, bits=0, stride=None, lower_bound=None, upper_bound=None, uninitialized=False, to_conv=None):
    '''
    :param name:
    :param bits:
    :param stride:
    :param lower_bound:
    :param upper_bound:
    :param to_conv:
    :return:
    '''
    if to_conv is not None:
        if isinstance(to_conv, Base):
            to_conv = to_conv.model
        if isinstance(to_conv, StridedInterval):
            # No conversion will be done
            return to_conv

        if type(to_conv) not in {int, long, BVV}: #pylint:disable=unidiomatic-typecheck
            raise ClaripyOperationError('Unsupported to_conv type %s' % type(to_conv))

        if stride is not None or lower_bound is not None or \
                        upper_bound is not None:
            raise ClaripyOperationError('You cannot specify both to_conv and other parameters at the same time.')

        if type(to_conv) is BVV: #pylint:disable=unidiomatic-typecheck
            bits = to_conv.bits
            to_conv_value = to_conv.value
        else:
            bits = bits
            to_conv_value = to_conv

        stride = 0
        lower_bound = to_conv_value
        upper_bound = to_conv_value

    bi = StridedInterval(name=name,
                         bits=bits,
                         stride=stride,
                         lower_bound=lower_bound,
                         upper_bound=upper_bound,
                         uninitialized=uninitialized)
    return bi


from .errors import ClaripyVSAError
from ..errors import ClaripyOperationError
from .bool_result import TrueResult, FalseResult, MaybeResult
from . import discrete_strided_interval_set
from .discrete_strided_interval_set import DiscreteStridedIntervalSet
from .valueset import ValueSet
from ..ast.base import Base
from ..bv import BVV
