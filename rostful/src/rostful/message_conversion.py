#!/usr/bin/env python
# Software License Agreement (BSD License)
#
# Copyright (c) 2012, Willow Garage, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of Willow Garage, Inc. nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import roslib
import rospy

import re
import string
from base64 import standard_b64encode, standard_b64decode


type_map = {
   "bool":    ["bool"],
   "int":     ["int8", "byte", "uint8", "char",
               "int16", "uint16", "int32", "uint32",
               "int64", "uint64", "float32", "float64"],
   "float":   ["float32", "float64"],
   "str":     ["string"],
   "unicode": ["string"],
   "long":    ["uint64"]
}
primitive_types = [bool, int, float]
string_types = [str, bytes]
list_types = [list, tuple]
ros_time_types = ["time", "duration"]
ros_primitive_types = ["bool", "byte", "char", "int8", "uint8", "int16",
                       "uint16", "int32", "uint32", "int64", "uint64",
                       "float32", "float64", "string"]
ros_header_types = ["Header", "std_msgs/Header", "roslib/Header"]
ros_binary_types = ["uint8[]", "char[]"]
list_braces = re.compile(r'\[[^\]]*\]')


class InvalidMessageException(Exception):
    def __init__(self, inst):
        Exception.__init__(self, "Unable to extract message values from %s instance" % type(inst).__name__)


class NonexistentFieldException(Exception):
    def __init__(self, basetype, fields):
        Exception.__init__(self, "Message type %s does not have a field %s" % (basetype, '.'.join(fields)))


class FieldTypeMismatchException(Exception):
    def __init__(self, roottype, fields, expected_type, found_type):
        if roottype == expected_type:
            Exception.__init__(self, "Expected a JSON object for type %s but received a %s" % (roottype, found_type))
        else:
            Exception.__init__(self, "%s message requires a %s for field %s, but got a %s" % (roottype, expected_type, '.'.join(fields), found_type))


def extract_values(inst):
    rostype = getattr(inst, "_type", None)
    if rostype is None:
        raise InvalidMessageException()
    return _from_inst(inst, rostype)
dump = extract_values

def populate_instance(msg, inst):
    """ Returns an instance of the provided class, with its fields populated
    according to the values in msg """
    return _to_inst(msg, inst._type, inst._type, inst)
#load = populate_instance

def _from_inst(inst, rostype):
    # Special case for uint8[], we base64 encode the string
    if rostype in ros_binary_types:
        return standard_b64encode(inst)

    # Check for time or duration
    if rostype in ros_time_types:
        return {"secs": inst.secs, "nsecs": inst.nsecs}

    # Check for primitive types
    if rostype in ros_primitive_types:
        return inst

    # Check if it's a list or tuple
    if type(inst) in list_types:
        return _from_list_inst(inst, rostype)

    # Assume it's otherwise a full ros msg object
    return _from_object_inst(inst, rostype)


def _from_list_inst(inst, rostype):
    # Can duck out early if the list is empty
    if len(inst) == 0:
        return []

    # Remove the list indicators from the rostype
    rostype = list_braces.sub("", rostype)
    
    # Shortcut for primitives
    if rostype in ros_primitive_types:
        return list(inst)

    # Call to _to_inst for every element of the list
    return [_from_inst(x, rostype) for x in inst]


def _from_object_inst(inst, rostype):
    # Create an empty dict then populate with values from the inst
    msg = {}
    for field_name, field_rostype in zip(inst.__slots__, inst._slot_types):
        field_inst = getattr(inst, field_name)
        msg[field_name] = _from_inst(field_inst, field_rostype)
    return msg


def _to_inst(msg, rostype, roottype, inst=None, stack=[]):
    # Check if it's uint8[], and if it's a string, try to b64decode
    if rostype in ros_binary_types:
        return _to_binary_inst(msg)

    # Check the type for time or rostime
    if rostype in ros_time_types:
        return _to_time_inst(msg, rostype, inst)

    # Check to see whether this is a primitive type
    if rostype in ros_primitive_types:
        return _to_primitive_inst(msg, rostype, roottype, stack)

    # Check whether we're dealing with a list type
    if inst is not None and type(inst) in list_types:
        return _to_list_inst(msg, rostype, roottype, inst, stack)

    # Otherwise, the type has to be a full ros msg type, so msg must be a dict
    if inst is None:
        inst = _get_msg_class(rostype)()

    return _to_object_inst(msg, rostype, roottype, inst, stack)


def _to_binary_inst(msg):
    if type(msg) in string_types:
        try:
            return standard_b64decode(msg)
        except:
            return msg
    else:
        try:
            return str(bytearray(msg))
        except:
            return msg


def _to_time_inst(msg, rostype, inst=None):
    # Create an instance if we haven't been provided with one
    if rostype == "time" and msg == "now":
        return rospy.get_rostime()

    if inst is None:
        if rostype == "time":
            inst = rospy.rostime.Time()
        elif rostype == "duration":
            inst = rospy.rostime.Duration()
        else:
            return None

    # Copy across the fields
    for field in ["secs", "nsecs"]:
        try:
            if field in msg:
                setattr(inst, field, msg[field])
        except TypeError:
            continue

    return inst


def _to_primitive_inst(msg, rostype, roottype, stack):
    # Typecheck the msg
    msgtype = type(msg)
    if msgtype in primitive_types and rostype in type_map[msgtype.__name__]:
        return msg
    elif msgtype in string_types and rostype in type_map[msgtype.__name__]:
        return msg.encode("ascii", "ignore")
    raise FieldTypeMismatchException(roottype, stack, rostype, msgtype)


def _to_list_inst(msg, rostype, roottype, inst, stack):
    # Typecheck the msg
    if type(msg) not in list_types:
        raise FieldTypeMismatchException(roottype, stack, rostype, type(msg))

    # Can duck out early if the list is empty
    if len(msg) == 0:
        return []

    # Remove the list indicators from the rostype
    rostype = list_braces.sub("", rostype)

    # Call to _to_inst for every element of the list
    return [_to_inst(x, rostype, roottype, None, stack) for x in msg]


def _to_object_inst(msg, rostype, roottype, inst, stack):
    # Typecheck the msg
    if type(msg) is not dict:
        raise FieldTypeMismatchException(roottype, stack, rostype, type(msg))

    # Substitute the correct time if we're an std_msgs/Header
    if rostype in ros_header_types:
        inst.stamp = rospy.get_rostime()

    inst_fields = dict(zip(inst.__slots__, inst._slot_types))

    for field_name in msg:
        # Add this field to the field stack
        field_stack = stack + [field_name]

        # Raise an exception if the msg contains a bad field
        if not field_name in inst_fields:
            raise NonexistentFieldException(roottype, field_stack)

        field_rostype = inst_fields[field_name]
        field_inst = getattr(inst, field_name)

        field_value = _to_inst(msg[field_name], field_rostype,
                    roottype, field_inst, field_stack)

        setattr(inst, field_name, field_value)

    return inst

from threading import Lock
# Variable containing the loaded classes
_loaded_msgs = {}
_loaded_srvs = {}
_msgs_lock = Lock()
_srvs_lock = Lock()


class InvalidTypeStringException(Exception):
    def __init__(self, typestring):
        Exception.__init__(self, "%s is not a valid type string" % typestring)


class InvalidPackageException(Exception):
    def __init__(self, package, original_exception):
        Exception.__init__(self,
           "Unable to load the manifest for package %s. Caused by: %s"
           % (package, original_exception.message)
       )


class InvalidModuleException(Exception):
    def __init__(self, modname, subname, original_exception):
        Exception.__init__(self,
           "Unable to import %s.%s from package %s. Caused by: %s"
           % (modname, subname, modname, str(original_exception))
        )


class InvalidClassException(Exception):
    def __init__(self, modname, subname, classname, original_exception):
        Exception.__init__(self,
           "Unable to import %s class %s from package %s. Caused by %s"
           % (subname, classname, modname, str(original_exception))
        )


def _get_msg_class(typestring):
    """ If not loaded, loads the specified msg class then returns an instance
    of it

    Throws various exceptions if loading the msg class fails """
    global _loaded_msgs, _msgs_lock
    return _get_class(typestring, "msg", _loaded_msgs, _msgs_lock)


def _get_srv_class(typestring):
    """ If not loaded, loads the specified srv class then returns an instance
    of it

    Throws various exceptions if loading the srv class fails """
    global _loaded_srvs, _srvs_lock
    return _get_class(typestring, "srv", _loaded_srvs, _srvs_lock)


def _get_class(typestring, subname, cache, lock):
    """ If not loaded, loads the specified class then returns an instance
    of it.

    Loaded classes are cached in the provided cache dict

    Throws various exceptions if loading the msg class fails """

    # First, see if we have this type string cached
    cls = _get_from_cache(cache, lock, typestring)
    if cls is not None:
        return cls

    # Now normalise the typestring
    modname, classname = _splittype(typestring)
    norm_typestring = modname + "/" + classname

    # Check to see if the normalised type string is cached
    cls = _get_from_cache(cache, lock, norm_typestring)
    if cls is not None:
        return cls

    # Load the class
    cls = _load_class(modname, subname, classname)

    # Cache the class for both the regular and normalised typestring
    _add_to_cache(cache, lock, typestring, cls)
    _add_to_cache(cache, lock, norm_typestring, cls)

    return cls


def _load_class(modname, subname, classname):
    """ Loads the manifest and imports the module that contains the specified
    type.

    Logic is similar to that of roslib.message.get_message_class, but we want
    more expressive exceptions.

    Returns the loaded module, or None on failure """
    global loaded_modules

    try:
        # roslib maintains a cache of loaded manifests, so no need to duplicate
        roslib.launcher.load_manifest(modname)
    except Exception as exc:
        raise InvalidPackageException(modname, exc)

    try:
        pypkg = __import__('%s.%s' % (modname, subname))
    except Exception as exc:
        raise InvalidModuleException(modname, subname, exc)

    try:
        return getattr(getattr(pypkg, subname), classname)
    except Exception as exc:
        raise InvalidClassException(modname, subname, classname, exc)


def _splittype(typestring):
    """ Split the string the / delimiter and strip out empty strings

    Performs similar logic to roslib.names.package_resource_name but is a bit
    more forgiving about excess slashes
    """
    splits = [x for x in typestring.split("/") if x]
    if len(splits) == 2:
        return splits
    raise InvalidTypeStringException(typestring)


def _add_to_cache(cache, lock, key, value):
    lock.acquire()
    cache[key] = value
    lock.release()


def _get_from_cache(cache, lock, key):
    """ Returns the value for the specified key from the cache.
    Locks the lock before doing anything. Returns None if key not in cache """
    lock.acquire()
    ret = None
    if key in cache:
        ret = cache[key]
    lock.release()
    return ret
