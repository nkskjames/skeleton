import dbus
import os
import cPickle
import json

BUS_PREFIX = 'org.openbmc'
OBJ_PREFIX = "/org/openbmc"
GPIO_DEV = '/sys/class/gpio'
BUS = "system"
CACHE_PATH = '/var/lib/obmc/inventory/'

## Utility functions
def getSystemName():
	#use filename as system name, strip off path and ext
	parts = __file__.replace('.pyc','').replace('.py','').split('/')
	return parts[len(parts)-1]

def getDBus():
	bus = None
	if (BUS == "session"):
		bus = dbus.SessionBus()
	else:
		bus = dbus.SystemBus()
	return bus

## Classes designed for being subclassed by Dbus object classes
class DbusProperties(dbus.service.Object):
	def __init__(self):
		dbus.service.Object.__init__(self)
		self.properties = {}
		self.object_path = ""

	@dbus.service.method(dbus.PROPERTIES_IFACE,
		in_signature='ss', out_signature='v')
	def Get(self, interface_name, property_name):
		d = self.GetAll(interface_name)
		try:
			v = d[property_name]
			return v
		except:
 			raise dbus.exceptions.DBusException(
				"org.freedesktop.UnknownPropery: "+property_name)

	@dbus.service.method(dbus.PROPERTIES_IFACE,
		in_signature='s', out_signature='a{sv}')
	def GetAll(self, interface_name):
		try:
			d = self.properties[interface_name]
			return d
 		except:
 			raise dbus.exceptions.DBusException(
				"org.freedesktop.UnknownInterface: "+interface_name)

	@dbus.service.method(dbus.PROPERTIES_IFACE,
		in_signature='ssv')
	def Set(self, interface_name, property_name, new_value):
		if (self.properties.has_key(interface_name) == False):
			self.properties[interface_name] = {}
		try:
			old_value = self.properties[interface_name][property_name] 
			if (old_value != new_value):
				self.properties[interface_name][property_name] = new_value
				self.PropertiesChanged(interface_name,{ property_name: new_value }, [])
				
		except:
        		self.properties[interface_name][property_name] = new_value
			self.PropertiesChanged(interface_name,{ property_name: new_value }, [])

	@dbus.service.method("org.openbmc.Object.Properties",
		in_signature='sa{sv}')
	def SetMultiple(self, interface_name, prop_dict):
		if (self.properties.has_key(interface_name) == False):
			self.properties[interface_name] = {}

		value_changed  = False
		for property_name in prop_dict:
			new_value = prop_dict[property_name]
			try:
				old_value = self.properties[interface_name][property_name] 
				if (old_value != new_value):
					self.properties[interface_name][property_name] = new_value
					value_changed = True
				
			except:
        			self.properties[interface_name][property_name] = new_value
				value_changed = True
		if (value_changed == True):
			self.PropertiesChanged(interface_name, prop_dict, [])
	
	@dbus.service.signal(dbus.PROPERTIES_IFACE,
		signature='sa{sv}as')
	def PropertiesChanged(self, interface_name, changed_properties,
		invalidated_properties):
		pass

class DbusPropertiesCached(DbusProperties):
	def __init__(self, object_path, cached_interfaces):
		DbusProperties.__init__(self)
		self.object_path = object_path
		self.cached_interfaces = cached_interfaces
		for intf in self.cached_interfaces.keys():
			self.load(intf, self.properties)

	def Set(self, interface_name, property_name, new_value):
		super(DbusPropertiesCached,self).Set(interface_name,property_name,new_value)
		if (self.cached_interfaces.has_key(interface_name)):
			self.save(interface_name,self.properties)

	def SetMultiple(self, interface_name, prop_dict):
		super(DbusPropertiesCached,self).SetMultiple(interface_name,prop_dict)
		if (self.cached_interfaces.has_key(interface_name)):
			self.save(interface_name,self.properties)

	def getCacheFilename(self,obj_path, iface_name):
		name = obj_path.replace('/','.')
		filename = CACHE_PATH+name[1:]+"@"+iface_name+".props"
		return filename

	def save(self,iface_name, properties):
		obj_path = self.object_path
		print "Caching: "+obj_path
		try:
			filename = self.getCacheFilename(obj_path, iface_name)
			output = open(filename, 'wb')
			try:
				## use json module to convert dbus datatypes
				props = json.dumps(properties[iface_name])
				prop_obj = json.loads(props)
				cPickle.dump(prop_obj,output)
			except Exception as e:
				print "ERROR: "+str(e)
			finally:
				output.close()
		except:
			print "ERROR opening cache file: "+filename


	def load(self, iface_name, properties):
		obj_path = self.object_path
		## overlay with pickled data
		filename=self.getCacheFilename(obj_path, iface_name)

		if (properties.has_key(iface_name) == False):
			properties[iface_name] = {}

		if (os.path.isfile(filename)):
			print "Loading from cache: "+filename
			try:
				p = open(filename, 'rb')
				data = cPickle.load(p)
				for prop in data.keys():
					## TODO: Dbus does not like empty lists since
					## it does not know signature.
					## If list is empty, change to empty string.
					if (isinstance(data[prop],list)):
						if (not data[prop]):
							data[prop] = ""
					properties[iface_name][prop] = data[prop]
			except Exception as e:
				print "ERROR: Loading cache file: " +str(e)
			finally:
				p.close()


class DbusObjectManager(dbus.service.Object):
	def __init__(self):
		dbus.service.Object.__init__(self)
		self.objects = {}

	def add(self,object_path,obj):
		self.objects[object_path] = obj
		self.InterfacesAdded(object_path,obj.properties)

	def remove(self,object_path):
		obj = self.objects.pop(object_path,None)
		obj.remove_from_connection()
		self.InterfacesRemoved(object_path,obj.properties.keys())

	def get(self,object_path):
		return self.objects[object_path]

	@dbus.service.method("org.freedesktop.DBus.ObjectManager",
		in_signature='', out_signature='a{oa{sa{sv}}}')
	def GetManagedObjects(self):
		data = {}
		for objpath in self.objects.keys():
			data[objpath] = self.objects[objpath].properties
		return data

	@dbus.service.signal("org.freedesktop.DBus.ObjectManager",
		signature='oa{sa{sv}}')
	def InterfacesAdded(self,object_path,properties):
		self.ObjectAdded(object_path,"")

	@dbus.service.signal("org.freedesktop.DBus.ObjectManager",
		signature='oas')
	def InterfacesRemoved(self,object_path,interfaces):
		pass

	## Legacy support, need to eventually refactor out
	@dbus.service.signal("org.openbmc.Object.ObjectMapper",
		signature='ss')
	def ObjectAdded(self,object_path,interface_name):
		pass

	## flattens interfaces
	@dbus.service.method('org.openbmc.Object.Enumerate',
		in_signature='', out_signature='a{sa{sv}}')
	def enumerate(self):
		data = {}
		for objpath in self.objects.keys():
			props = self.objects[objpath].properties
			data[objpath] = { }
			for iface in props.keys():
				data[objpath].update(props[iface])
				
		return data
		



