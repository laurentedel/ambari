#!/usr/bin/env ambari-python-wrap
"""
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import re
import os
import sys
from math import ceil

from stack_advisor import DefaultStackAdvisor


class HDP206StackAdvisor(DefaultStackAdvisor):

  def getComponentLayoutValidations(self, services, hosts):
    """Returns array of Validation objects about issues with hostnames components assigned to"""
    items = []

    # Validating NAMENODE and SECONDARY_NAMENODE are on different hosts if possible
    hostsList = [host["Hosts"]["host_name"] for host in hosts["items"]]
    hostsCount = len(hostsList)

    componentsListList = [service["components"] for service in services["services"]]
    componentsList = [item for sublist in componentsListList for item in sublist]
    nameNodeHosts = [component["StackServiceComponents"]["hostnames"] for component in componentsList if component["StackServiceComponents"]["component_name"] == "NAMENODE"]
    secondaryNameNodeHosts = [component["StackServiceComponents"]["hostnames"] for component in componentsList if component["StackServiceComponents"]["component_name"] == "SECONDARY_NAMENODE"]

    # Validating cardinality
    for component in componentsList:
      if component["StackServiceComponents"]["cardinality"] is not None:
         componentName = component["StackServiceComponents"]["component_name"]
         componentDisplayName = component["StackServiceComponents"]["display_name"]
         componentHostsCount = 0
         if component["StackServiceComponents"]["hostnames"] is not None:
           componentHostsCount = len(component["StackServiceComponents"]["hostnames"])
         cardinality = str(component["StackServiceComponents"]["cardinality"])
         # cardinality types: null, 1+, 1-2, 1, ALL
         message = None
         if "+" in cardinality:
           hostsMin = int(cardinality[:-1])
           if componentHostsCount < hostsMin:
             message = "At least {0} {1} components should be installed in cluster.".format(hostsMin, componentDisplayName)
         elif "-" in cardinality:
           nums = cardinality.split("-")
           hostsMin = int(nums[0])
           hostsMax = int(nums[1])
           if componentHostsCount > hostsMax or componentHostsCount < hostsMin:
             message = "Between {0} and {1} {2} components should be installed in cluster.".format(hostsMin, hostsMax, componentDisplayName)
         elif "ALL" == cardinality:
           if componentHostsCount != hostsCount:
             message = "{0} component should be installed on all hosts in cluster.".format(componentDisplayName)
         else:
           if componentHostsCount != int(cardinality):
             message = "Exactly {0} {1} components should be installed in cluster.".format(int(cardinality), componentDisplayName)

         if message is not None:
           items.append({"type": 'host-component', "level": 'ERROR', "message": message, "component-name": componentName})

    # Validating host-usage
    usedHostsListList = [component["StackServiceComponents"]["hostnames"] for component in componentsList if not self.isComponentNotValuable(component)]
    usedHostsList = [item for sublist in usedHostsListList for item in sublist]
    nonUsedHostsList = [item for item in hostsList if item not in usedHostsList]
    for host in nonUsedHostsList:
      items.append( { "type": 'host-component', "level": 'ERROR', "message": 'Host is not used', "host": str(host) } )

    return items

  def getServiceConfigurationRecommenderDict(self):
    return {
      "YARN": self.recommendYARNConfigurations,
      "MAPREDUCE2": self.recommendMapReduce2Configurations,
      "HDFS": self.recommendHDFSConfigurations,
      "HBASE": self.recommendHbaseConfigurations,
      "AMBARI_METRICS": self.recommendAmsConfigurations
    }

  def putProperty(self, config, configType, services=None):
    userConfigs = {}
    changedConfigs = []
    # if services parameter, prefer values, set by user
    if services:
      if 'configurations' in services.keys():
        userConfigs = services['configurations']
      if 'changed-configurations' in services.keys():
        changedConfigs = services["changed-configurations"]

    if configType not in config:
      config[configType] = {}
    if"properties" not in config[configType]:
      config[configType]["properties"] = {}
    def appendProperty(key, value):
      if {'type': configType, 'name': key} in changedConfigs:
        config[configType]["properties"][key] = userConfigs[configType]['properties'][key]
      else:
        config[configType]["properties"][key] = str(value)
    return appendProperty

  def putPropertyAttribute(self, config, configType):
    if configType not in config:
      config[configType] = {}
    def appendPropertyAttribute(key, attribute, attributeValue):
      if "property_attributes" not in config[configType]:
        config[configType]["property_attributes"] = {}
      if key not in config[configType]["property_attributes"]:
        config[configType]["property_attributes"][key] = {}
      config[configType]["property_attributes"][key][attribute] = attributeValue if isinstance(attributeValue, list) else str(attributeValue)
    return appendPropertyAttribute

  def recommendYARNConfigurations(self, configurations, clusterData, services, hosts):
    putYarnProperty = self.putProperty(configurations, "yarn-site", services)
    putYarnEnvProperty = self.putProperty(configurations, "yarn-env", services)
    nodemanagerMinRam = 1048576 # 1TB in mb
    if "referenceNodeManagerHost" in clusterData:
      nodemanagerMinRam = min(clusterData["referenceNodeManagerHost"]["total_mem"]/1024, nodemanagerMinRam)
    putYarnProperty('yarn.nodemanager.resource.memory-mb', int(round(min(clusterData['containers'] * clusterData['ramPerContainer'], nodemanagerMinRam))))
    putYarnProperty('yarn.scheduler.minimum-allocation-mb', int(clusterData['ramPerContainer']))
    putYarnProperty('yarn.scheduler.maximum-allocation-mb', int(configurations["yarn-site"]["properties"]["yarn.nodemanager.resource.memory-mb"]))
    putYarnEnvProperty('min_user_id', self.get_system_min_uid())
    containerExecutorGroup = 'hadoop'
    if 'cluster-env' in services['configurations'] and 'user_group' in services['configurations']['cluster-env']['properties']:
      containerExecutorGroup = services['configurations']['cluster-env']['properties']['user_group']
    putYarnProperty("yarn.nodemanager.linux-container-executor.group", containerExecutorGroup)

  def recommendMapReduce2Configurations(self, configurations, clusterData, services, hosts):
    putMapredProperty = self.putProperty(configurations, "mapred-site", services)
    putMapredProperty('yarn.app.mapreduce.am.resource.mb', int(clusterData['amMemory']))
    putMapredProperty('yarn.app.mapreduce.am.command-opts', "-Xmx" + str(int(round(0.8 * clusterData['amMemory']))) + "m")
    putMapredProperty('mapreduce.map.memory.mb', clusterData['mapMemory'])
    putMapredProperty('mapreduce.reduce.memory.mb', int(clusterData['reduceMemory']))
    putMapredProperty('mapreduce.map.java.opts', "-Xmx" + str(int(round(0.8 * clusterData['mapMemory']))) + "m")
    putMapredProperty('mapreduce.reduce.java.opts', "-Xmx" + str(int(round(0.8 * clusterData['reduceMemory']))) + "m")
    putMapredProperty('mapreduce.task.io.sort.mb', min(int(round(0.4 * clusterData['mapMemory'])), 1024))

  def recommendHadoopProxyUsers (self, configurations, services, hosts):
    servicesList = [service["StackServices"]["service_name"] for service in services["services"]]
    users = {}

    if 'forced-configurations' not in services:
      services["forced-configurations"] = []

    if "HDFS" in servicesList:
      hdfs_user = None
      if "hadoop-env" in services["configurations"] and "hdfs_user" in services["configurations"]["hadoop-env"]["properties"]:
        hdfs_user = services["configurations"]["hadoop-env"]["properties"]["hdfs_user"]
        if not hdfs_user in users and hdfs_user is not None:
          users[hdfs_user] = {"propertyHosts" : "*","propertyGroups" : "*", "config" : "hadoop-env", "propertyName" : "hdfs_user"}

    if "OOZIE" in servicesList:
      oozie_user = None
      if "oozie-env" in services["configurations"] and "oozie_user" in services["configurations"]["oozie-env"]["properties"]:
        oozie_user = services["configurations"]["oozie-env"]["properties"]["oozie_user"]
        oozieServerrHost = self.getHostWithComponent("OOZIE", "OOZIE_SERVER", services, hosts)
        if oozieServerrHost is not None:
          oozieServerHostName = oozieServerrHost["Hosts"]["public_host_name"]
          if not oozie_user in users and oozie_user is not None:
            users[oozie_user] = {"propertyHosts" : oozieServerHostName,"propertyGroups" : "*", "config" : "oozie-env", "propertyName" : "oozie_user"}

    if "HIVE" in servicesList:
      hive_user = None
      webhcat_user = None
      if "hive-env" in services["configurations"] and "hive_user" in services["configurations"]["hive-env"]["properties"] \
              and "webhcat_user" in services["configurations"]["hive-env"]["properties"]:
        hive_user = services["configurations"]["hive-env"]["properties"]["hive_user"]
        webhcat_user = services["configurations"]["hive-env"]["properties"]["webhcat_user"]
        proxy_user_group = None
        if "hadoop-env" in services["configurations"] and "proxyuser_group" in services["configurations"]["hadoop-env"]["properties"]:
          proxy_user_group = services["configurations"]["hadoop-env"]["properties"]["proxyuser_group"]
        hiveServerrHost = self.getHostWithComponent("HIVE", "HIVE_SERVER", services, hosts)
        if hiveServerrHost is not None:
          hiveServerHostName = hiveServerrHost["Hosts"]["public_host_name"]
          if not hive_user in users and hive_user is not None:
            users[hive_user] = {"propertyHosts" : hiveServerHostName,"propertyGroups" : "*", "config" : "hive-env", "propertyName" : "hive_user"}
          if not webhcat_user in users and not None in [webhcat_user , proxy_user_group]:
            users[webhcat_user] = {"propertyHosts" : hiveServerHostName,"propertyGroups" : proxy_user_group, "config" : "hive-env", "propertyName" : "webhcat_user"}

    if "FALCON" in servicesList:
      falconUser = None
      if "falcon-env" in services["configurations"] and "falcon_user" in services["configurations"]["falcon-env"]["properties"]:
        falconUser = services["configurations"]["falcon-env"]["properties"]["falcon_user"]
        proxy_user_group = None
        if "hadoop-env" in services["configurations"] and "proxyuser_group" in services["configurations"]["hadoop-env"]["properties"]:
          proxy_user_group = services["configurations"]["hadoop-env"]["properties"]["proxyuser_group"]
        if not falconUser in users and not None in [proxy_user_group, falconUser]:
          users[falconUser] = {"propertyHosts" : "*","propertyGroups" : proxy_user_group, "config" : "falcon-env", "propertyName" : "falcon_user"}

    putCoreSiteProperty = self.putProperty(configurations, "core-site", services)
    putCoreSitePropertyAttribute = self.putPropertyAttribute(configurations, "core-site")

    for user_name, user_properties in users.iteritems():
      # Add properties "hadoop.proxyuser.*.hosts", "hadoop.proxyuser.*.groups" to core-site for all users
      putCoreSiteProperty("hadoop.proxyuser.{0}.hosts".format(user_name) , user_properties["propertyHosts"])
      putCoreSiteProperty("hadoop.proxyuser.{0}.groups".format(user_name) , user_properties["propertyGroups"])

      # Remove old properties if user was renamed
      userOldValue = getOldValue(self, services, user_properties["config"], user_properties["propertyName"])
      if userOldValue is not None:
        putCoreSitePropertyAttribute("hadoop.proxyuser.{0}.hosts".format(userOldValue), 'delete', 'true')
        putCoreSitePropertyAttribute("hadoop.proxyuser.{0}.groups".format(userOldValue), 'delete', 'true')
        services["forced-configurations"].append({"type" : "core-site", "name" : "hadoop.proxyuser.{0}.hosts".format(userOldValue)})
        services["forced-configurations"].append({"type" : "core-site", "name" : "hadoop.proxyuser.{0}.groups".format(userOldValue)})
        services["forced-configurations"].append({"type" : "core-site", "name" : "hadoop.proxyuser.{0}.hosts".format(user_name)})
        services["forced-configurations"].append({"type" : "core-site", "name" : "hadoop.proxyuser.{0}.groups".format(user_name)})

  def recommendHDFSConfigurations(self, configurations, clusterData, services, hosts):
    putHDFSProperty = self.putProperty(configurations, "hadoop-env", services)
    putHDFSProperty('namenode_heapsize', max(int(clusterData['totalAvailableRam'] / 2), 1024))
    putHDFSProperty = self.putProperty(configurations, "hadoop-env", services)
    putHDFSProperty('namenode_opt_newsize', max(int(clusterData['totalAvailableRam'] / 8), 128))
    putHDFSProperty = self.putProperty(configurations, "hadoop-env", services)
    putHDFSProperty('namenode_opt_maxnewsize', max(int(clusterData['totalAvailableRam'] / 8), 256))

    # recommendations for "hadoop.proxyuser.*.hosts", "hadoop.proxyuser.*.groups" properties in core-site
    self.recommendHadoopProxyUsers(configurations, services, hosts)

  def recommendHbaseConfigurations(self, configurations, clusterData, services, hosts):
    # recommendations for HBase env config
    putHbaseProperty = self.putProperty(configurations, "hbase-env", services)
    putHbaseProperty('hbase_regionserver_heapsize', int(clusterData['hbaseRam']) * 1024)
    putHbaseProperty('hbase_master_heapsize', int(clusterData['hbaseRam']) * 1024)

    # recommendations for HBase site config
    putHbaseSiteProperty = self.putProperty(configurations, "hbase-site", services)

    if 'hbase-site' in services['configurations'] and 'hbase.superuser' in services['configurations']['hbase-site']['properties'] \
      and 'hbase-env' in services['configurations'] and 'hbase_user' in services['configurations']['hbase-env']['properties'] \
      and services['configurations']['hbase-env']['properties']['hbase_user'] != services['configurations']['hbase-site']['properties']['hbase.superuser']:
      putHbaseSiteProperty("hbase.superuser", services['configurations']['hbase-env']['properties']['hbase_user'])

  def getAmsMemoryRecommendation(self, services, hosts):
    # MB per sink in hbase heapsize
    HEAP_PER_MASTER_COMPONENT = 50
    HEAP_PER_SLAVE_COMPONENT = 10

    schMemoryMap = {
      "HDFS": {
        "NAMENODE": HEAP_PER_MASTER_COMPONENT,
        "DATANODE": HEAP_PER_SLAVE_COMPONENT
      },
      "YARN": {
        "RESOURCEMANAGER": HEAP_PER_MASTER_COMPONENT,
      },
      "HBASE": {
        "HBASE_MASTER": HEAP_PER_MASTER_COMPONENT,
        "HBASE_REGIONSERVER": HEAP_PER_SLAVE_COMPONENT
      },
      "ACCUMULO": {
        "ACCUMULO_MASTER": HEAP_PER_MASTER_COMPONENT,
        "ACCUMULO_TSERVER": HEAP_PER_SLAVE_COMPONENT
      },
      "KAFKA": {
        "KAFKA_BROKER": HEAP_PER_MASTER_COMPONENT
      },
      "FLUME": {
        "FLUME_HANDLER": HEAP_PER_SLAVE_COMPONENT
      },
      "STORM": {
        "NIMBUS": HEAP_PER_MASTER_COMPONENT,
      },
      "AMBARI_METRICS": {
        "METRICS_COLLECTOR": HEAP_PER_MASTER_COMPONENT,
        "METRICS_MONITOR": HEAP_PER_SLAVE_COMPONENT
      }
    }
    total_sinks_count = 0
    # minimum heap size
    hbase_heapsize = 500
    for serviceName, componentsDict in schMemoryMap.items():
      for componentName, multiplier in componentsDict.items():
        schCount = len(
          self.getHostsWithComponent(serviceName, componentName, services,
                                     hosts))
        hbase_heapsize += int((schCount * multiplier) ** 0.9)
        total_sinks_count += schCount
    collector_heapsize = int(hbase_heapsize/4 if hbase_heapsize > 2048 else 512)

    return round_to_n(collector_heapsize), round_to_n(hbase_heapsize), total_sinks_count

  def recommendAmsConfigurations(self, configurations, clusterData, services, hosts):
    putAmsEnvProperty = self.putProperty(configurations, "ams-env", services)
    putAmsHbaseSiteProperty = self.putProperty(configurations, "ams-hbase-site", services)
    putTimelineServiceProperty = self.putProperty(configurations, "ams-site", services)
    putHbaseEnvProperty = self.putProperty(configurations, "ams-hbase-env", services)

    amsCollectorHosts = self.getComponentHostNames(services, "AMBARI_METRICS", "METRICS_COLLECTOR")

    rootDir = "file:///var/lib/ambari-metrics-collector/hbase"
    tmpDir = "/var/lib/ambari-metrics-collector/hbase-tmp"
    if "ams-hbase-site" in services["configurations"]:
      if "hbase.rootdir" in services["configurations"]["ams-hbase-site"]["properties"]:
        rootDir = services["configurations"]["ams-hbase-site"]["properties"]["hbase.rootdir"]
      if "hbase.tmp.dir" in services["configurations"]["ams-hbase-site"]["properties"]:
        tmpDir = services["configurations"]["ams-hbase-site"]["properties"]["hbase.tmp.dir"]

    mountpoints = ["/"]
    for collectorHostName in amsCollectorHosts:
      for host in hosts["items"]:
        if host["Hosts"]["host_name"] == collectorHostName:
          mountpoints = self.getPreferredMountPoints(host["Hosts"])
          break
    if not rootDir.startswith("hdfs://"):
      rootDir = re.sub("^file:///|/", "", rootDir, count=1)
      rootDir = "file://" + os.path.join(mountpoints[0], rootDir)
    tmpDir = re.sub("^file:///|/", "", tmpDir, count=1)
    if len(mountpoints) > 1 and not rootDir.startswith("hdfs://"):
      tmpDir = os.path.join(mountpoints[1], tmpDir)
    else:
      tmpDir = os.path.join(mountpoints[0], tmpDir)
    putAmsHbaseSiteProperty("hbase.rootdir", rootDir)
    putAmsHbaseSiteProperty("hbase.tmp.dir", tmpDir)

    collector_heapsize, hbase_heapsize, total_sinks_count = self.getAmsMemoryRecommendation(services, hosts)

    putAmsEnvProperty("metrics_collector_heapsize", str(collector_heapsize) + "m")

    # blockCache = 0.3, memstore = 0.35, phoenix-server = 0.15, phoenix-client = 0.25
    putAmsHbaseSiteProperty("hfile.block.cache.size", 0.3)
    putAmsHbaseSiteProperty("hbase.hregion.memstore.flush.size", 134217728)
    putAmsHbaseSiteProperty("hbase.regionserver.global.memstore.upperLimit", 0.35)
    putAmsHbaseSiteProperty("hbase.regionserver.global.memstore.lowerLimit", 0.3)
    putTimelineServiceProperty("timeline.metrics.host.aggregator.ttl", 86400)

    if len(amsCollectorHosts) > 1:
      pass
    else:
      # blockCache = 0.3, memstore = 0.3, phoenix-server = 0.2, phoenix-client = 0.3
      if total_sinks_count >= 2000:
        putAmsHbaseSiteProperty("hbase.regionserver.handler.count", 60)
        putAmsHbaseSiteProperty("hbase.regionserver.hlog.blocksize", 134217728)
        putAmsHbaseSiteProperty("hbase.regionserver.maxlogs", 64)
        putAmsHbaseSiteProperty("hbase.hregion.memstore.flush.size", 268435456)
        putAmsHbaseSiteProperty("hbase.regionserver.global.memstore.upperLimit", 0.3)
        putAmsHbaseSiteProperty("hbase.regionserver.global.memstore.lowerLimit", 0.25)
        putAmsHbaseSiteProperty("phoenix.query.maxGlobalMemoryPercentage", 20)
        putTimelineServiceProperty("phoenix.query.maxGlobalMemoryPercentage", 30)
        hbase_xmn_size = '512m'
      elif total_sinks_count >= 500:
        putAmsHbaseSiteProperty("hbase.regionserver.handler.count", 60)
        putAmsHbaseSiteProperty("hbase.regionserver.hlog.blocksize", 134217728)
        putAmsHbaseSiteProperty("hbase.regionserver.maxlogs", 64)
        putAmsHbaseSiteProperty("hbase.hregion.memstore.flush.size", 268435456)
        hbase_xmn_size = '512m'
      elif total_sinks_count >= 250:
        hbase_xmn_size = '256m'
      else:
        hbase_xmn_size = '128m'
      pass

    # Embedded mode heap size : master + regionserver
    if rootDir.startswith("hdfs://"):
      putHbaseEnvProperty("hbase_master_heapsize", "512m")
      putHbaseEnvProperty("hbase_regionserver_heapsize", str(hbase_heapsize) + "m")
      putHbaseEnvProperty("regionserver_xmn_size", hbase_xmn_size)
    else:
      putHbaseEnvProperty("hbase_master_heapsize", str(hbase_heapsize) + "m")
      putHbaseEnvProperty("hbase_master_xmn_size", hbase_xmn_size)

    #split points
    scriptDir = os.path.dirname(os.path.abspath(__file__))
    metricsDir = os.path.join(scriptDir, '../../../../common-services/AMBARI_METRICS/0.1.0/package')
    serviceMetricsDir = os.path.join(metricsDir, 'files', 'service-metrics')
    sys.path.append(os.path.join(metricsDir, 'scripts'))
    mode = 'distributed' if rootDir.startswith("hdfs://") else 'embedded'
    servicesList = [service["StackServices"]["service_name"] for service in services["services"]]

    from split_points import FindSplitPointsForAMSRegions

    ams_hbase_site = None
    ams_hbase_env = None

    # Overriden properties form the UI
    if "ams-hbase-site" in services["configurations"]:
      ams_hbase_site = services["configurations"]["ams-hbase-site"]["properties"]
    if "ams-hbase-env" in services["configurations"]:
       ams_hbase_env = services["configurations"]["ams-hbase-env"]["properties"]

    # Recommendations
    if not ams_hbase_site:
      ams_hbase_site = configurations["ams-hbase-site"]["properties"]
    if not ams_hbase_env:
      ams_hbase_env = configurations["ams-hbase-env"]["properties"]

    split_point_finder = FindSplitPointsForAMSRegions(
      ams_hbase_site, ams_hbase_env, serviceMetricsDir, mode, servicesList)

    result = split_point_finder.get_split_points()
    precision_splits = ' '
    aggregate_splits = ' '
    if result.precision:
      precision_splits = result.precision
    if result.aggregate:
      aggregate_splits = result.aggregate
    putTimelineServiceProperty("timeline.metrics.host.aggregate.splitpoints", ','.join(precision_splits))
    putTimelineServiceProperty("timeline.metrics.cluster.aggregate.splitpoints", ','.join(aggregate_splits))

    pass

  def getHostsWithComponent(self, serviceName, componentName, services, hosts):
    if services is not None and hosts is not None and serviceName in [service["StackServices"]["service_name"] for service in services["services"]]:
      service = [serviceEntry for serviceEntry in services["services"] if serviceEntry["StackServices"]["service_name"] == serviceName][0]
      components = [componentEntry for componentEntry in service["components"] if componentEntry["StackServiceComponents"]["component_name"] == componentName]
      if (len(components) > 0 and len(components[0]["StackServiceComponents"]["hostnames"]) > 0):
        componentHostnames = components[0]["StackServiceComponents"]["hostnames"]
        componentHosts = [host for host in hosts["items"] if host["Hosts"]["host_name"] in componentHostnames]
        return componentHosts
    return []

  def getHostWithComponent(self, serviceName, componentName, services, hosts):
    componentHosts = self.getHostsWithComponent(serviceName, componentName, services, hosts)
    if (len(componentHosts) > 0):
      return componentHosts[0]
    return None

  def getHostComponentsByCategories(self, hostname, categories, services, hosts):
    components = []
    if services is not None and hosts is not None:
      for service in services["services"]:
          components.extend([componentEntry for componentEntry in service["components"]
                              if componentEntry["StackServiceComponents"]["component_category"] in categories
                              and hostname in componentEntry["StackServiceComponents"]["hostnames"]])
    return components

  def getConfigurationClusterSummary(self, servicesList, hosts, components, services):

    hBaseInstalled = False
    if 'HBASE' in servicesList:
      hBaseInstalled = True

    cluster = {
      "cpu": 0,
      "disk": 0,
      "ram": 0,
      "hBaseInstalled": hBaseInstalled,
      "components": components
    }

    if len(hosts["items"]) > 0:
      nodeManagerHosts = self.getHostsWithComponent("YARN", "NODEMANAGER", services, hosts)
      # NodeManager host with least memory is generally used in calculations as it will work in larger hosts.
      if nodeManagerHosts is not None and len(nodeManagerHosts) > 0:
        nodeManagerHost = nodeManagerHosts[0];
        for nmHost in nodeManagerHosts:
          if nmHost["Hosts"]["total_mem"] < nodeManagerHost["Hosts"]["total_mem"]:
            nodeManagerHost = nmHost
        host = nodeManagerHost["Hosts"]
        cluster["referenceNodeManagerHost"] = host
      else:
        host = hosts["items"][0]["Hosts"]
      cluster["referenceHost"] = host
      cluster["cpu"] = host["cpu_count"]
      cluster["disk"] = len(host["disk_info"])
      cluster["ram"] = int(host["total_mem"] / (1024 * 1024))

    ramRecommendations = [
      {"os":1, "hbase":1},
      {"os":2, "hbase":1},
      {"os":2, "hbase":2},
      {"os":4, "hbase":4},
      {"os":6, "hbase":8},
      {"os":8, "hbase":8},
      {"os":8, "hbase":8},
      {"os":12, "hbase":16},
      {"os":24, "hbase":24},
      {"os":32, "hbase":32},
      {"os":64, "hbase":64}
    ]
    index = {
      cluster["ram"] <= 4: 0,
      4 < cluster["ram"] <= 8: 1,
      8 < cluster["ram"] <= 16: 2,
      16 < cluster["ram"] <= 24: 3,
      24 < cluster["ram"] <= 48: 4,
      48 < cluster["ram"] <= 64: 5,
      64 < cluster["ram"] <= 72: 6,
      72 < cluster["ram"] <= 96: 7,
      96 < cluster["ram"] <= 128: 8,
      128 < cluster["ram"] <= 256: 9,
      256 < cluster["ram"]: 10
    }[1]
    cluster["reservedRam"] = ramRecommendations[index]["os"]
    cluster["hbaseRam"] = ramRecommendations[index]["hbase"]

    cluster["minContainerSize"] = {
      cluster["ram"] <= 4: 256,
      4 < cluster["ram"] <= 8: 512,
      8 < cluster["ram"] <= 24: 1024,
      24 < cluster["ram"]: 2048
    }[1]

    totalAvailableRam = cluster["ram"] - cluster["reservedRam"]
    if cluster["hBaseInstalled"]:
      totalAvailableRam -= cluster["hbaseRam"]
    cluster["totalAvailableRam"] = max(512, totalAvailableRam * 1024)
    '''containers = max(3, min (2*cores,min (1.8*DISKS,(Total available RAM) / MIN_CONTAINER_SIZE))))'''
    cluster["containers"] = round(max(3,
                                min(2 * cluster["cpu"],
                                    min(ceil(1.8 * cluster["disk"]),
                                            cluster["totalAvailableRam"] / cluster["minContainerSize"]))))

    '''ramPerContainers = max(2GB, RAM - reservedRam - hBaseRam) / containers'''
    cluster["ramPerContainer"] = abs(cluster["totalAvailableRam"] / cluster["containers"])
    '''If greater than 1GB, value will be in multiples of 512.'''
    if cluster["ramPerContainer"] > 1024:
      cluster["ramPerContainer"] = int(cluster["ramPerContainer"] / 512) * 512

    cluster["mapMemory"] = int(cluster["ramPerContainer"])
    cluster["reduceMemory"] = cluster["ramPerContainer"]
    cluster["amMemory"] = max(cluster["mapMemory"], cluster["reduceMemory"])

    return cluster

  def getConfigurationsValidationItems(self, services, hosts):
    """Returns array of Validation objects about issues with configuration values provided in services"""
    items = []

    recommendations = self.recommendConfigurations(services, hosts)
    recommendedDefaults = recommendations["recommendations"]["blueprint"]["configurations"]

    configurations = services["configurations"]
    for service in services["services"]:
      serviceName = service["StackServices"]["service_name"]
      validator = self.validateServiceConfigurations(serviceName)
      if validator is not None:
        for siteName, method in validator.items():
          if siteName in recommendedDefaults:
            siteProperties = getSiteProperties(configurations, siteName)
            if siteProperties is not None:
              siteRecommendations = recommendedDefaults[siteName]["properties"]
              print("SiteName: %s, method: %s\n" % (siteName, method.__name__))
              print("Site properties: %s\n" % str(siteProperties))
              print("Recommendations: %s\n********\n" % str(siteRecommendations))
              resultItems = method(siteProperties, siteRecommendations, configurations, services, hosts)
              items.extend(resultItems)

    clusterWideItems = self.validateClusterConfigurations(configurations, services, hosts)
    items.extend(clusterWideItems)
    self.validateMinMax(items, recommendedDefaults, configurations)
    return items

  def validateClusterConfigurations(self, configurations, services, hosts):
    validationItems = []

    return self.toConfigurationValidationProblems(validationItems, "")

  def getServiceConfigurationValidators(self):
    return {
      "HDFS": {"hadoop-env": self.validateHDFSConfigurationsEnv},
      "MAPREDUCE2": {"mapred-site": self.validateMapReduce2Configurations},
      "YARN": {"yarn-site": self.validateYARNConfigurations},
      "HBASE": {"hbase-env": self.validateHbaseEnvConfigurations},
      "AMBARI_METRICS": {"ams-hbase-site": self.validateAmsHbaseSiteConfigurations,
              "ams-hbase-env": self.validateAmsHbaseEnvConfigurations,
              "ams-site": self.validateAmsSiteConfigurations}
    }

  def validateMinMax(self, items, recommendedDefaults, configurations):

    # required for casting to the proper numeric type before comparison
    def convertToNumber(number):
      try:
        return int(number)
      except ValueError:
        return float(number)

    for configName in configurations:
      validationItems = []
      if configName in recommendedDefaults and "property_attributes" in recommendedDefaults[configName]:
        for propertyName in recommendedDefaults[configName]["property_attributes"]:
          if propertyName in configurations[configName]["properties"]:
            if "maximum" in recommendedDefaults[configName]["property_attributes"][propertyName] and \
                propertyName in recommendedDefaults[configName]["properties"]:
              userValue = convertToNumber(configurations[configName]["properties"][propertyName])
              maxValue = convertToNumber(recommendedDefaults[configName]["property_attributes"][propertyName]["maximum"])
              if userValue > maxValue:
                validationItems.extend([{"config-name": propertyName, "item": self.getWarnItem("Value is greater than the recommended maximum of {0} ".format(maxValue))}])
            if "minimum" in recommendedDefaults[configName]["property_attributes"][propertyName] and \
                    propertyName in recommendedDefaults[configName]["properties"]:
              userValue = convertToNumber(configurations[configName]["properties"][propertyName])
              minValue = convertToNumber(recommendedDefaults[configName]["property_attributes"][propertyName]["minimum"])
              if userValue < minValue:
                validationItems.extend([{"config-name": propertyName, "item": self.getWarnItem("Value is less than the recommended minimum of {0} ".format(minValue))}])
      items.extend(self.toConfigurationValidationProblems(validationItems, configName))
    pass

  def validateAmsSiteConfigurations(self, properties, recommendedDefaults, configurations, services, hosts):
    validationItems = []

    op_mode = properties.get("timeline.metrics.service.operation.mode")
    correct_op_mode_item = None
    if op_mode not in ("embedded", "distributed"):
      correct_op_mode_item = self.getErrorItem("Correct value should be set.")
      pass

    validationItems.extend([{"config-name":'timeline.metrics.service.operation.mode', "item": correct_op_mode_item }])
    return self.toConfigurationValidationProblems(validationItems, "ams-site")

  def validateAmsHbaseSiteConfigurations(self, properties, recommendedDefaults, configurations, services, hosts):

    amsCollectorHosts = self.getComponentHostNames(services, "AMBARI_METRICS", "METRICS_COLLECTOR")
    ams_site = getSiteProperties(configurations, "ams-site")

    collector_heapsize, hbase_heapsize, total_sinks_count = self.getAmsMemoryRecommendation(services, hosts)
    recommendedDiskSpace = 10485760
    # TODO validate configuration for multiple AMBARI_METRICS collectors
    if len(amsCollectorHosts) > 1:
      pass
    else:
      if total_sinks_count > 2000:
        recommendedDiskSpace  = 104857600  # * 1k == 100 Gb
      elif total_sinks_count > 500:
        recommendedDiskSpace  = 52428800  # * 1k == 50 Gb
      elif total_sinks_count > 250:
        recommendedDiskSpace  = 20971520  # * 1k == 20 Gb

    validationItems = []

    rootdir_item = None
    op_mode = ams_site.get("timeline.metrics.service.operation.mode")
    hbase_rootdir = properties.get("hbase.rootdir")
    hbase_tmpdir = properties.get("hbase.tmp.dir")
    if op_mode == "distributed" and not hbase_rootdir.startswith("hdfs://"):
      rootdir_item = self.getWarnItem("In distributed mode hbase.rootdir should point to HDFS. Collector will operate in embedded mode otherwise.")
      pass

    distributed_item = None
    distributed = properties.get("hbase.cluster.distributed")
    if hbase_rootdir and hbase_rootdir.startswith("hdfs://") and not distributed.lower() == "true":
      distributed_item = self.getErrorItem("Distributed property should be set to true if hbase.rootdir points to HDFS.")

    validationItems.extend([{"config-name":'hbase.rootdir', "item": rootdir_item },
                            {"config-name":'hbase.cluster.distributed', "item": distributed_item }])

    for collectorHostName in amsCollectorHosts:
      for host in hosts["items"]:
        if host["Hosts"]["host_name"] == collectorHostName:
          validationItems.extend([{"config-name": 'hbase.rootdir', "item": self.validatorEnoughDiskSpace(properties, 'hbase.rootdir', host["Hosts"], recommendedDiskSpace)}])
          validationItems.extend([{"config-name": 'hbase.rootdir', "item": self.validatorNotRootFs(properties, recommendedDefaults, 'hbase.rootdir', host["Hosts"])}])
          validationItems.extend([{"config-name": 'hbase.tmp.dir', "item": self.validatorNotRootFs(properties, recommendedDefaults, 'hbase.tmp.dir', host["Hosts"])}])

          if not hbase_rootdir.startswith("hdfs"):
            mountPoints = []
            for mountPoint in host["Hosts"]["disk_info"]:
              mountPoints.append(mountPoint["mountpoint"])
            hbase_rootdir_mountpoint = getMountPointForDir(hbase_rootdir, mountPoints)
            hbase_tmpdir_mountpoint = getMountPointForDir(hbase_tmpdir, mountPoints)
            preferred_mountpoints = self.getPreferredMountPoints(host['Hosts'])
            # hbase.rootdir and hbase.tmp.dir shouldn't point to the same partition
            # if multiple preferred_mountpoints exist
            if hbase_rootdir_mountpoint == hbase_tmpdir_mountpoint and \
              len(preferred_mountpoints) > 1:
              item = self.getWarnItem("Consider not using {0} partition for storing metrics temporary data. "
                                      "{0} partition is already used as hbase.rootdir to store metrics data".format(hbase_tmpdir_mountpoint))
              validationItems.extend([{"config-name":'hbase.tmp.dir', "item": item}])

            # if METRICS_COLLECTOR is co-hosted with DATANODE
            # cross-check dfs.datanode.data.dir and hbase.rootdir
            # they shouldn't share same disk partition IO
            dn_hosts = self.getComponentHostNames(services, "HDFS", "DATANODE")
            hdfs_site = getSiteProperties(configurations, "hdfs-site")
            dfs_datadirs = hdfs_site.get("dfs.datanode.data.dir").split(",") if hdfs_site and "dfs.datanode.data.dir" in hdfs_site else []
            if dn_hosts and collectorHostName in dn_hosts and ams_site and \
              dfs_datadirs and len(preferred_mountpoints) > len(dfs_datadirs):
              for dfs_datadir in dfs_datadirs:
                dfs_datadir_mountpoint = getMountPointForDir(dfs_datadir, mountPoints)
                if dfs_datadir_mountpoint == hbase_rootdir_mountpoint:
                  item = self.getWarnItem("Consider not using {0} partition for storing metrics data. "
                                          "{0} is already used by datanode to store HDFS data".format(hbase_rootdir_mountpoint))
                  validationItems.extend([{"config-name":'hbase.rootdir', "item": item}])
                  break

    return self.toConfigurationValidationProblems(validationItems, "ams-hbase-site")

  def validateAmsHbaseEnvConfigurations(self, properties, recommendedDefaults, configurations, services, hosts):
    regionServerItem = self.validatorLessThenDefaultValue(properties, recommendedDefaults, "hbase_regionserver_heapsize") ## FIXME if new service added
    masterItem = self.validatorLessThenDefaultValue(properties, recommendedDefaults, "hbase_master_heapsize")
    ams_env = getSiteProperties(configurations, "ams-env")
    amsHbaseSite = getSiteProperties(configurations, "ams-hbase-site")
    logDirItem = self.validatorEqualsPropertyItem(properties, "hbase_log_dir",
                                                  ams_env, "metrics_collector_log_dir")
    validationItems = []
    masterHostItem = None

    if masterItem is None:
      hostMasterComponents = {}

      for service in services["services"]:
        for component in service["components"]:
          if component["StackServiceComponents"]["hostnames"] is not None:
            for hostName in component["StackServiceComponents"]["hostnames"]:
              if self.isMasterComponent(component):
                if hostName not in hostMasterComponents.keys():
                  hostMasterComponents[hostName] = []
                hostMasterComponents[hostName].append(component["StackServiceComponents"]["component_name"])

      amsCollectorHosts = self.getComponentHostNames(services, "AMBARI_METRICS", "METRICS_COLLECTOR")
      for collectorHostName in amsCollectorHosts:
        for host in hosts["items"]:
          if host["Hosts"]["host_name"] == collectorHostName:
            # AMS Collector co-hosted with other master components in bigger clusters
            if len(hosts['items']) > 31 and \
              len(hostMasterComponents[collectorHostName]) > 2 and \
              host["Hosts"]["total_mem"] < 32*1024*1024: # <32 Gb(total_mem in k)
              masterHostMessage = "Host {0} is used by multiple master components ({1}). " \
                                  "It is recommended to use a separate host for the " \
                                  "Ambari Metrics Collector component and ensure " \
                                  "the host has sufficient memory available."

              masterHostItem = self.getWarnItem(
                masterHostMessage.format(
                  collectorHostName, str(", ".join(hostMasterComponents[collectorHostName]))))

          # Check for unused RAM on AMS Collector node
          hostComponents = []
          for service in services["services"]:
            for component in service["components"]:
              if component["StackServiceComponents"]["hostnames"] is not None:
                if collectorHostName in component["StackServiceComponents"]["hostnames"]:
                  hostComponents.append(component["StackServiceComponents"]["component_name"])

          requiredMemory = getMemorySizeRequired(hostComponents, configurations)
          unusedMemory = host["Hosts"]["total_mem"] * 1024 - requiredMemory # in bytes
          hbase_rootdir = amsHbaseSite.get("hbase.rootdir")
          if unusedMemory > 4294967296:  # warn user, if more than 4GB RAM is unused
            heapPropertyToIncrease = "hbase_regionserver_heapsize" if hbase_rootdir.startswith("hdfs://") else "hbase_master_heapsize"
            xmnPropertyToIncrease = "regionserver_xmn_size" if hbase_rootdir.startswith("hdfs://") else "hbase_master_xmn_size"
            collector_heapsize = int((unusedMemory - 4294967296)/5) + to_number(ams_env.get("metrics_collector_heapsize"))*1048576
            hbase_heapsize = int((unusedMemory - 4294967296)*4/5) + to_number(properties.get(heapPropertyToIncrease))*1048576

            if hbase_heapsize/1048576 > 2048:
              xmn_size = '512'
            elif hbase_heapsize/1048576 > 1024:
              xmn_size = '256'
            else:
              xmn_size = '128'

            msg = "{0} MB RAM is unused on the host {1} based on components " \
                  "assigned. Consider allocating  {2} MB to " \
                  "metrics_collector_heapsize in ams-env, " \
                  "{3} MB to {4} in ams-hbase-env and " \
                  "{5} MB to {6} in ams-hbase-env"

            unusedMemoryHbaseItem = self.getWarnItem(msg.format(unusedMemory/1048576, collectorHostName, collector_heapsize/1048576, hbase_heapsize/1048576, heapPropertyToIncrease, xmn_size, xmnPropertyToIncrease))
            validationItems.extend([{"config-name": heapPropertyToIncrease, "item": unusedMemoryHbaseItem}])
      pass

    # Check RS memory in distributed mode since we set default as 512m
    hbase_site = getSiteProperties(configurations, "ams-hbase-site")
    hbase_rootdir = hbase_site.get("hbase.rootdir")
    regionServerMinMemItem = None
    if hbase_rootdir and hbase_rootdir.startswith("hdfs://"):
      regionServerMinMemItem = self.validateMinMemorySetting(properties, 1024, 'hbase_regionserver_heapsize')

    validationItems.extend([
      {"config-name": "hbase_regionserver_heapsize", "item": regionServerItem},
      {"config-name": "hbase_regionserver_heapsize", "item": regionServerMinMemItem},
      {"config-name": "hbase_master_heapsize", "item": masterItem},
      {"config-name": "hbase_master_heapsize", "item": masterHostItem},
      {"config-name": "hbase_log_dir", "item": logDirItem}
    ])
    return self.toConfigurationValidationProblems(validationItems, "ams-hbase-env")


  def validateServiceConfigurations(self, serviceName):
    return self.getServiceConfigurationValidators().get(serviceName, None)

  def toConfigurationValidationProblems(self, validationProblems, siteName):
    result = []
    for validationProblem in validationProblems:
      validationItem = validationProblem.get("item", None)
      if validationItem is not None:
        problem = {"type": 'configuration', "level": validationItem["level"], "message": validationItem["message"],
                   "config-type": siteName, "config-name": validationProblem["config-name"] }
        result.append(problem)
    return result

  def getWarnItem(self, message):
    return {"level": "WARN", "message": message}

  def getErrorItem(self, message):
    return {"level": "ERROR", "message": message}

  def getPreferredMountPoints(self, hostInfo):

    # '/etc/resolv.conf', '/etc/hostname', '/etc/hosts' are docker specific mount points
    undesirableMountPoints = ["/", "/home", "/etc/resolv.conf", "/etc/hosts",
                              "/etc/hostname"]
    undesirableFsTypes = ["devtmpfs", "tmpfs", "vboxsf", "CDFS"]
    mountPoints = []
    if hostInfo and "disk_info" in hostInfo:
      mountPointsDict = {}
      for mountpoint in hostInfo["disk_info"]:
        if not (mountpoint["mountpoint"] in undesirableMountPoints or
                mountpoint["mountpoint"].startswith(("/boot", "/mnt")) or
                mountpoint["type"] in undesirableFsTypes or
                mountpoint["available"] == str(0)):
          mountPointsDict[mountpoint["mountpoint"]] = to_number(mountpoint["available"])
      if mountPointsDict:
        mountPoints = sorted(mountPointsDict, key=mountPointsDict.get, reverse=True)
    mountPoints.append("/")
    return mountPoints

  def validatorNotRootFs(self, properties, recommendedDefaults, propertyName, hostInfo):
    if not propertyName in properties:
      return self.getErrorItem("Value should be set")
    dir = properties[propertyName]
    if dir.startswith("hdfs://") or dir == recommendedDefaults.get(propertyName):
      return None

    dir = re.sub("^file://", "", dir, count=1)
    mountPoints = []
    for mountPoint in hostInfo["disk_info"]:
      mountPoints.append(mountPoint["mountpoint"])
    mountPoint = getMountPointForDir(dir, mountPoints)

    if "/" == mountPoint and self.getPreferredMountPoints(hostInfo)[0] != mountPoint:
      return self.getWarnItem("It is not recommended to use root partition for {0}".format(propertyName))

    return None

  def validatorEnoughDiskSpace(self, properties, propertyName, hostInfo, reqiuredDiskSpace):
    if not propertyName in properties:
      return self.getErrorItem("Value should be set")
    dir = properties[propertyName]
    if dir.startswith("hdfs://"):
      return None

    dir = re.sub("^file://", "", dir, count=1)
    mountPoints = {}
    for mountPoint in hostInfo["disk_info"]:
      mountPoints[mountPoint["mountpoint"]] = to_number(mountPoint["available"])
    mountPoint = getMountPointForDir(dir, mountPoints.keys())

    if not mountPoints:
      return self.getErrorItem("No disk info found on host %s" % hostInfo["host_name"])

    if mountPoints[mountPoint] < reqiuredDiskSpace:
      msg = "Ambari Metrics disk space requirements not met. \n" \
            "Recommended disk space for partition {0} is {1}G"
      return self.getWarnItem(msg.format(mountPoint, reqiuredDiskSpace/1048576)) # in Gb
    return None

  def validatorLessThenDefaultValue(self, properties, recommendedDefaults, propertyName):
    if propertyName not in recommendedDefaults:
      # If a property name exists in say hbase-env and hbase-site (which is allowed), then it will exist in the
      # "properties" dictionary, but not necessarily in the "recommendedDefaults" dictionary". In this case, ignore it.
      return None

    if not propertyName in properties:
      return self.getErrorItem("Value should be set")
    value = to_number(properties[propertyName])
    if value is None:
      return self.getErrorItem("Value should be integer")
    defaultValue = to_number(recommendedDefaults[propertyName])
    if defaultValue is None:
      return None
    if value < defaultValue:
      return self.getWarnItem("Value is less than the recommended default of {0}".format(defaultValue))
    return None

  def validatorEqualsPropertyItem(self, properties1, propertyName1,
                                  properties2, propertyName2,
                                  emptyAllowed=False):
    if not propertyName1 in properties1:
      return self.getErrorItem("Value should be set for %s" % propertyName1)
    if not propertyName2 in properties2:
      return self.getErrorItem("Value should be set for %s" % propertyName2)
    value1 = properties1.get(propertyName1)
    if value1 is None and not emptyAllowed:
      return self.getErrorItem("Empty value for %s" % propertyName1)
    value2 = properties2.get(propertyName2)
    if value2 is None and not emptyAllowed:
      return self.getErrorItem("Empty value for %s" % propertyName2)
    if value1 != value2:
      return self.getWarnItem("It is recommended to set equal values "
             "for properties {0} and {1}".format(propertyName1, propertyName2))

    return None

  def validateMinMemorySetting(self, properties, defaultValue, propertyName):
    if not propertyName in properties:
      return self.getErrorItem("Value should be set")
    if defaultValue is None:
      return self.getErrorItem("Config's default value can't be null or undefined")

    value = properties[propertyName]
    if value is None:
      return self.getErrorItem("Value can't be null or undefined")
    try:
      valueInt = to_number(value)
      # TODO: generify for other use cases
      defaultValueInt = int(str(defaultValue).strip())
      if valueInt < defaultValueInt:
        return self.getWarnItem("Value is less than the minimum recommended default of -Xmx" + str(defaultValue))
    except:
      return None

    return None


  def validateXmxValue(self, properties, recommendedDefaults, propertyName):
    if not propertyName in properties:
      return self.getErrorItem("Value should be set")
    value = properties[propertyName]
    defaultValue = recommendedDefaults[propertyName]
    if defaultValue is None:
      return self.getErrorItem("Config's default value can't be null or undefined")
    if not checkXmxValueFormat(value) and checkXmxValueFormat(defaultValue):
      # Xmx is in the default-value but not the value, should be an error
      return self.getErrorItem('Invalid value format')
    if not checkXmxValueFormat(defaultValue):
      # if default value does not contain Xmx, then there is no point in validating existing value
      return None
    valueInt = formatXmxSizeToBytes(getXmxSize(value))
    defaultValueXmx = getXmxSize(defaultValue)
    defaultValueInt = formatXmxSizeToBytes(defaultValueXmx)
    if valueInt < defaultValueInt:
      return self.getWarnItem("Value is less than the recommended default of -Xmx" + defaultValueXmx)
    return None

  def validateMapReduce2Configurations(self, properties, recommendedDefaults, configurations, services, hosts):
    validationItems = [ {"config-name": 'mapreduce.map.java.opts', "item": self.validateXmxValue(properties, recommendedDefaults, 'mapreduce.map.java.opts')},
                        {"config-name": 'mapreduce.reduce.java.opts', "item": self.validateXmxValue(properties, recommendedDefaults, 'mapreduce.reduce.java.opts')},
                        {"config-name": 'mapreduce.task.io.sort.mb', "item": self.validatorLessThenDefaultValue(properties, recommendedDefaults, 'mapreduce.task.io.sort.mb')},
                        {"config-name": 'mapreduce.map.memory.mb', "item": self.validatorLessThenDefaultValue(properties, recommendedDefaults, 'mapreduce.map.memory.mb')},
                        {"config-name": 'mapreduce.reduce.memory.mb', "item": self.validatorLessThenDefaultValue(properties, recommendedDefaults, 'mapreduce.reduce.memory.mb')},
                        {"config-name": 'yarn.app.mapreduce.am.resource.mb', "item": self.validatorLessThenDefaultValue(properties, recommendedDefaults, 'yarn.app.mapreduce.am.resource.mb')},
                        {"config-name": 'yarn.app.mapreduce.am.command-opts', "item": self.validateXmxValue(properties, recommendedDefaults, 'yarn.app.mapreduce.am.command-opts')} ]
    return self.toConfigurationValidationProblems(validationItems, "mapred-site")

  def validateYARNConfigurations(self, properties, recommendedDefaults, configurations, services, hosts):
    clusterEnv = getSiteProperties(configurations, "cluster-env")
    validationItems = [ {"config-name": 'yarn.nodemanager.resource.memory-mb', "item": self.validatorLessThenDefaultValue(properties, recommendedDefaults, 'yarn.nodemanager.resource.memory-mb')},
                        {"config-name": 'yarn.scheduler.minimum-allocation-mb', "item": self.validatorLessThenDefaultValue(properties, recommendedDefaults, 'yarn.scheduler.minimum-allocation-mb')},
                        {"config-name": 'yarn.nodemanager.linux-container-executor.group', "item": self.validatorEqualsPropertyItem(properties, "yarn.nodemanager.linux-container-executor.group", clusterEnv, "user_group")},
                        {"config-name": 'yarn.scheduler.maximum-allocation-mb', "item": self.validatorLessThenDefaultValue(properties, recommendedDefaults, 'yarn.scheduler.maximum-allocation-mb')} ]
    return self.toConfigurationValidationProblems(validationItems, "yarn-site")

  def validateHbaseEnvConfigurations(self, properties, recommendedDefaults, configurations, services, hosts):
    hbase_site = getSiteProperties(configurations, "hbase-site")
    validationItems = [ {"config-name": 'hbase_regionserver_heapsize', "item": self.validatorLessThenDefaultValue(properties, recommendedDefaults, 'hbase_regionserver_heapsize')},
                        {"config-name": 'hbase_master_heapsize', "item": self.validatorLessThenDefaultValue(properties, recommendedDefaults, 'hbase_master_heapsize')},
                        {"config-name": "hbase_user", "item": self.validatorEqualsPropertyItem(properties, "hbase_user", hbase_site, "hbase.superuser")} ]
    return self.toConfigurationValidationProblems(validationItems, "hbase-env")

  def validateHDFSConfigurationsEnv(self, properties, recommendedDefaults, configurations, services, hosts):
    validationItems = [ {"config-name": 'namenode_heapsize', "item": self.validatorLessThenDefaultValue(properties, recommendedDefaults, 'namenode_heapsize')},
                        {"config-name": 'namenode_opt_newsize', "item": self.validatorLessThenDefaultValue(properties, recommendedDefaults, 'namenode_opt_newsize')},
                        {"config-name": 'namenode_opt_maxnewsize', "item": self.validatorLessThenDefaultValue(properties, recommendedDefaults, 'namenode_opt_maxnewsize')}]
    return self.toConfigurationValidationProblems(validationItems, "hadoop-env")

  def getMastersWithMultipleInstances(self):
    return ['ZOOKEEPER_SERVER', 'HBASE_MASTER']

  def getNotValuableComponents(self):
    return ['JOURNALNODE', 'ZKFC', 'GANGLIA_MONITOR']

  def getNotPreferableOnServerComponents(self):
    return ['GANGLIA_SERVER', 'METRICS_COLLECTOR']

  def getCardinalitiesDict(self):
    return {
      'ZOOKEEPER_SERVER': {"min": 3},
      'HBASE_MASTER': {"min": 1},
      }

  def getComponentLayoutSchemes(self):
    return {
      'NAMENODE': {"else": 0},
      'SECONDARY_NAMENODE': {"else": 1},
      'HBASE_MASTER': {6: 0, 31: 2, "else": 3},

      'HISTORYSERVER': {31: 1, "else": 2},
      'RESOURCEMANAGER': {31: 1, "else": 2},

      'OOZIE_SERVER': {6: 1, 31: 2, "else": 3},

      'HIVE_SERVER': {6: 1, 31: 2, "else": 4},
      'HIVE_METASTORE': {6: 1, 31: 2, "else": 4},
      'WEBHCAT_SERVER': {6: 1, 31: 2, "else": 4},
      'METRICS_COLLECTOR': {3: 2, 6: 2, 31: 3, "else": 5},
    }

  def get_system_min_uid(self):
    login_defs = '/etc/login.defs'
    uid_min_tag = 'UID_MIN'
    comment_tag = '#'
    uid_min = uid_default = '1000'
    uid = None

    if os.path.exists(login_defs):
      with open(login_defs, 'r') as f:
        data = f.read().split('\n')
        # look for uid_min_tag in file
        uid = filter(lambda x: uid_min_tag in x, data)
        # filter all lines, where uid_min_tag was found in comments
        uid = filter(lambda x: x.find(comment_tag) > x.find(uid_min_tag) or x.find(comment_tag) == -1, uid)

      if uid is not None and len(uid) > 0:
        uid = uid[0]
        comment = uid.find(comment_tag)
        tag = uid.find(uid_min_tag)
        if comment == -1:
          uid_tag = tag + len(uid_min_tag)
          uid_min = uid[uid_tag:].strip()
        elif comment > tag:
          uid_tag = tag + len(uid_min_tag)
          uid_min = uid[uid_tag:comment].strip()

    # check result for value
    try:
      int(uid_min)
    except ValueError:
      return uid_default

    return uid_min

  def mergeValidators(self, parentValidators, childValidators):
    for service, configsDict in childValidators.iteritems():
      if service not in parentValidators:
        parentValidators[service] = {}
      parentValidators[service].update(configsDict)

def getOldValue(self, services, configType, propertyName):
  if services:
    if 'changed-configurations' in services.keys():
      changedConfigs = services["changed-configurations"]
      for changedConfig in changedConfigs:
        if changedConfig["type"] == configType and changedConfig["name"]== propertyName and "old_value" in changedConfig:
          return changedConfig["old_value"]
  return None

# Validation helper methods
def getSiteProperties(configurations, siteName):
  siteConfig = configurations.get(siteName)
  if siteConfig is None:
    return None
  return siteConfig.get("properties")

def to_number(s):
  try:
    return int(re.sub("\D", "", s))
  except ValueError:
    return None

def checkXmxValueFormat(value):
  p = re.compile('-Xmx(\d+)(b|k|m|g|p|t|B|K|M|G|P|T)?')
  matches = p.findall(value)
  return len(matches) == 1

def getXmxSize(value):
  p = re.compile("-Xmx(\d+)(.?)")
  result = p.findall(value)[0]
  if len(result) > 1:
    # result[1] - is a space or size formatter (b|k|m|g etc)
    return result[0] + result[1].lower()
  return result[0]

def formatXmxSizeToBytes(value):
  value = value.lower()
  if len(value) == 0:
    return 0
  modifier = value[-1]

  if modifier == ' ' or modifier in "0123456789":
    modifier = 'b'
  m = {
    modifier == 'b': 1,
    modifier == 'k': 1024,
    modifier == 'm': 1024 * 1024,
    modifier == 'g': 1024 * 1024 * 1024,
    modifier == 't': 1024 * 1024 * 1024 * 1024,
    modifier == 'p': 1024 * 1024 * 1024 * 1024 * 1024
    }[1]
  return to_number(value) * m

def getPort(address):
  """
  Extracts port from the address like 0.0.0.0:1019
  """
  if address is None:
    return None
  m = re.search(r'(?:http(?:s)?://)?([\w\d.]*):(\d{1,5})', address)
  if m is not None:
    return int(m.group(2))
  else:
    return None

def isSecurePort(port):
  """
  Returns True if port is root-owned at *nix systems
  """
  if port is not None:
    return port < 1024
  else:
    return False

def getMountPointForDir(dir, mountPoints):
  """
  :param dir: Directory to check, even if it doesn't exist.
  :return: Returns the closest mount point as a string for the directory.
  if the "dir" variable is None, will return None.
  If the directory does not exist, will return "/".
  """
  bestMountFound = None
  if dir:
    dir = re.sub("^file://", "", dir, count=1).strip().lower()

    # If the path is "/hadoop/hdfs/data", then possible matches for mounts could be
    # "/", "/hadoop/hdfs", and "/hadoop/hdfs/data".
    # So take the one with the greatest number of segments.
    for mountPoint in mountPoints:
      if dir.startswith(mountPoint):
        if bestMountFound is None:
          bestMountFound = mountPoint
        elif bestMountFound.count(os.path.sep) < os.path.join(mountPoint, "").count(os.path.sep):
          bestMountFound = mountPoint

  return bestMountFound

def getHeapsizeProperties():
  return { "NAMENODE": [{"config-name": "hadoop-env",
                         "property": "namenode_heapsize",
                         "default": "1024m"}],
           "DATANODE": [{"config-name": "hadoop-env",
                         "property": "dtnode_heapsize",
                         "default": "1024m"}],
           "REGIONSERVER": [{"config-name": "hbase-env",
                             "property": "hbase_regionserver_heapsize",
                             "default": "1024m"}],
           "HBASE_MASTER": [{"config-name": "hbase-env",
                             "property": "hbase_master_heapsize",
                             "default": "1024m"}],
           "HIVE_CLIENT": [{"config-name": "hive-site",
                            "property": "hive.heapsize",
                            "default": "1024m"}],
           "HISTORYSERVER": [{"config-name": "mapred-env",
                              "property": "jobhistory_heapsize",
                              "default": "1024m"}],
           "OOZIE_SERVER": [{"config-name": "oozie-env",
                             "property": "oozie_heapsize",
                             "default": "1024m"}],
           "RESOURCEMANAGER": [{"config-name": "yarn-env",
                                "property": "resourcemanager_heapsize",
                                "default": "1024m"}],
           "NODEMANAGER": [{"config-name": "yarn-env",
                            "property": "nodemanager_heapsize",
                            "default": "1024m"}],
           "APP_TIMELINE_SERVER": [{"config-name": "yarn-env",
                                    "property": "apptimelineserver_heapsize",
                                    "default": "1024m"}],
           "ZOOKEEPER_SERVER": [{"config-name": "zookeeper-env",
                                 "property": "zookeeper_heapsize",
                                 "default": "1024m"}],
           "METRICS_COLLECTOR": [{"config-name": "ams-hbase-env",
                                   "property": "hbase_master_heapsize",
                                   "default": "1024m"},
                                 {"config-name": "ams-env",
                                   "property": "metrics_collector_heapsize",
                                   "default": "512m"}],
           }

def getMemorySizeRequired(components, configurations):
  totalMemoryRequired = 512*1024*1024 # 512Mb for OS needs
  for component in components:
    if component in getHeapsizeProperties().keys():
      heapSizeProperties = getHeapsizeProperties()[component]
      for heapSizeProperty in heapSizeProperties:
        try:
          properties = configurations[heapSizeProperty["config-name"]]["properties"]
          heapsize = properties[heapSizeProperty["property"]]
        except KeyError:
          heapsize = heapSizeProperty["default"]

        # Assume Mb if no modifier
        if len(heapsize) > 1 and heapsize[-1] in '0123456789':
          heapsize = str(heapsize) + "m"

        totalMemoryRequired += formatXmxSizeToBytes(heapsize)

  return totalMemoryRequired

def round_to_n(mem_size, n=128):
  return int(round(mem_size / float(n))) * int(n)