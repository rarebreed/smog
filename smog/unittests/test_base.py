__author__ = 'stoner'

from smog.tests.base import *
import smog.nova

base = BaseStack(username="admin", password="ce5071308a604820",
                 auth_url="http://10.35.162.37:5000/v2.0/",
                 tenant_name="admin")
ks2 = base.keystone
print(ks2)
print(smog.nova.list_instances(base.nova))
