/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.apache.ambari.server.controller.internal;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import junit.framework.Assert;

import org.apache.ambari.server.api.services.AmbariMetaInfo;
import org.apache.ambari.server.controller.ResourceProviderFactory;
import org.apache.ambari.server.controller.predicate.AndPredicate;
import org.apache.ambari.server.controller.spi.Predicate;
import org.apache.ambari.server.controller.spi.Request;
import org.apache.ambari.server.controller.spi.ResourceProvider;
import org.apache.ambari.server.controller.utilities.PredicateBuilder;
import org.apache.ambari.server.controller.utilities.PropertyHelper;
import org.apache.ambari.server.orm.GuiceJpaInitializer;
import org.apache.ambari.server.orm.InMemoryDefaultTestModule;
import org.apache.ambari.server.orm.dao.ClusterVersionDAO;
import org.apache.ambari.server.orm.dao.RepositoryVersionDAO;
import org.apache.ambari.server.orm.dao.StackDAO;
import org.apache.ambari.server.orm.entities.ClusterVersionEntity;
import org.apache.ambari.server.orm.entities.RepositoryVersionEntity;
import org.apache.ambari.server.orm.entities.StackEntity;
import org.apache.ambari.server.state.OperatingSystemInfo;
import org.apache.ambari.server.state.RepositoryVersionState;
import org.apache.ambari.server.state.StackId;
import org.apache.ambari.server.state.StackInfo;
import org.apache.ambari.server.state.stack.UpgradePack;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.mockito.Mockito;
import org.mockito.invocation.InvocationOnMock;
import org.mockito.stubbing.Answer;

import com.google.common.collect.Sets;
import com.google.gson.Gson;
import com.google.inject.Guice;
import com.google.inject.Injector;
import com.google.inject.persist.PersistService;

/**
 * RepositoryVersionResourceProvider tests.
 */
public class RepositoryVersionResourceProviderTest {

  private static Injector injector;

  private static String jsonStringRedhat6 = "[{\"OperatingSystems\":{\"os_type\":\"redhat6\"},\"repositories\":[]}]";
  private static String jsonStringRedhat7 = "[{\"OperatingSystems\":{\"os_type\":\"redhat7\"},\"repositories\":[]}]";

  @Before
  public void before() throws Exception {
    final Set<String> validVersions = Sets.newHashSet("1.1", "1.1-17", "1.1.1.1", "1.1.343432.2", "1.1.343432.2-234234324");
    final AmbariMetaInfo ambariMetaInfo = Mockito.mock(AmbariMetaInfo.class);
    final ClusterVersionDAO clusterVersionDAO = Mockito.mock(ClusterVersionDAO.class);
    final InMemoryDefaultTestModule injectorModule = new InMemoryDefaultTestModule() {
      @Override
      protected void configure() {
        super.configure();
        bind(AmbariMetaInfo.class).toInstance(ambariMetaInfo);
        bind(ClusterVersionDAO.class).toInstance(clusterVersionDAO);
      };
    };
    injector = Guice.createInjector(injectorModule);

    final StackInfo stackInfo = new StackInfo() {
      @Override
      public Map<String, UpgradePack> getUpgradePacks() {
        final Map<String, UpgradePack> map = new HashMap<String, UpgradePack>();
        final UpgradePack pack1 = new UpgradePack() {
          @Override
          public String getTarget() {
            return "1.1.*.*";
          }
        };
        final UpgradePack pack2 = new UpgradePack() {
          @Override
          public String getTarget() {
            return "1.1.*.*";
          }
        };
        map.put("pack1", pack1);
        map.put("pack2", pack2);
        return map;
      }
    };
    Mockito.when(ambariMetaInfo.getStack(Mockito.anyString(), Mockito.anyString())).thenAnswer(new Answer<StackInfo>() {

      @Override
      public StackInfo answer(InvocationOnMock invocation) throws Throwable {
        final String stack = invocation.getArguments()[0].toString();
        final String version = invocation.getArguments()[1].toString();
        if (stack.equals("HDP") && validVersions.contains(version)) {
          return stackInfo;
        } else {
          throw new Exception("error");
        }
      }

    });

    Mockito.when(ambariMetaInfo.getUpgradePacks(Mockito.anyString(), Mockito.anyString())).thenAnswer(new Answer<Map<String, UpgradePack>>() {

      @Override
      public Map<String, UpgradePack> answer(InvocationOnMock invocation)
          throws Throwable {
        return stackInfo.getUpgradePacks();
      }

    });

    final HashSet<OperatingSystemInfo> osInfos = new HashSet<OperatingSystemInfo>();
    osInfos.add(new OperatingSystemInfo("redhat6"));
    osInfos.add(new OperatingSystemInfo("redhat7"));
    Mockito.when(ambariMetaInfo.getOperatingSystems(Mockito.anyString(), Mockito.anyString())).thenAnswer(new Answer<Set<OperatingSystemInfo>>() {

      @Override
      public Set<OperatingSystemInfo> answer(InvocationOnMock invocation)
          throws Throwable {
        final String stack = invocation.getArguments()[0].toString();
        final String version = invocation.getArguments()[1].toString();
        if (stack.equals("HDP") && validVersions.contains(version)) {
          return osInfos;
        } else {
          return new HashSet<OperatingSystemInfo>();
        }
      }
    });

    Mockito.when(
        clusterVersionDAO.findByStackAndVersion(Mockito.anyString(),
            Mockito.anyString(), Mockito.anyString())).thenAnswer(
        new Answer<List<ClusterVersionEntity>>() {

      @Override
      public List<ClusterVersionEntity> answer(InvocationOnMock invocation)
          throws Throwable {
        final String stack = invocation.getArguments()[0].toString();
        final String version = invocation.getArguments()[1].toString();
        if (stack.equals("HDP-1.1") && version.equals("1.1.1.1")) {
          final List<ClusterVersionEntity> notEmptyList = new ArrayList<ClusterVersionEntity>();
          notEmptyList.add(null);
          return notEmptyList;
        } else {
          final List<ClusterVersionEntity> clusterVersions = new ArrayList<ClusterVersionEntity>();
          final RepositoryVersionEntity repositoryVersion = new RepositoryVersionEntity();
          repositoryVersion.setId(1L);
          final ClusterVersionEntity installFailedVersion = new ClusterVersionEntity();
          installFailedVersion.setState(RepositoryVersionState.INSTALL_FAILED);
          installFailedVersion.setRepositoryVersion(repositoryVersion);
          clusterVersions.add(installFailedVersion);
          return clusterVersions;
        }
      }
    });

    injector.getInstance(GuiceJpaInitializer.class);

    // because AmbariMetaInfo is mocked, the stacks are never inserted into
    // the database, so insert HDP-1.1 manually
    StackDAO stackDAO = injector.getInstance(StackDAO.class);
    StackEntity stackEntity = new StackEntity();
    stackEntity.setStackName("HDP");
    stackEntity.setStackVersion("1.1");
    stackDAO.create(stackEntity);
  }

  @Test
  public void testCreateResources() throws Exception {
    final ResourceProvider provider = injector.getInstance(ResourceProviderFactory.class).getRepositoryVersionResourceProvider();

    final Set<Map<String, Object>> propertySet = new LinkedHashSet<Map<String, Object>>();
    final Map<String, Object> properties = new LinkedHashMap<String, Object>();
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_DISPLAY_NAME_PROPERTY_ID, "name");
    properties.put(RepositoryVersionResourceProvider.SUBRESOURCE_OPERATING_SYSTEMS_PROPERTY_ID, new Gson().fromJson("[{\"OperatingSystems/os_type\":\"redhat6\",\"repositories\":[{\"Repositories/repo_id\":\"1\",\"Repositories/repo_name\":\"1\",\"Repositories/base_url\":\"1\"}]}]", Object.class));
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_NAME_PROPERTY_ID, "HDP");
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_UPGRADE_PACK_PROPERTY_ID, "pack1");
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_VERSION_PROPERTY_ID, "1.1");
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_REPOSITORY_VERSION_PROPERTY_ID, "1.1.1.1");
    propertySet.add(properties);

    final Predicate predicateStackName = new PredicateBuilder().property(RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_NAME_PROPERTY_ID).equals("HDP").toPredicate();
    final Predicate predicateStackVersion = new PredicateBuilder().property(RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_VERSION_PROPERTY_ID).equals("1.1").toPredicate();
    final Request getRequest = PropertyHelper.getReadRequest(RepositoryVersionResourceProvider.REPOSITORY_VERSION_DISPLAY_NAME_PROPERTY_ID);
    Assert.assertEquals(0, provider.getResources(getRequest, new AndPredicate(predicateStackName, predicateStackVersion)).size());

    final Request createRequest = PropertyHelper.getCreateRequest(propertySet, null);
    provider.createResources(createRequest);

    Assert.assertEquals(1, provider.getResources(getRequest, new AndPredicate(predicateStackName, predicateStackVersion)).size());
  }

  @Test
  public void testGetResources() throws Exception {
    StackDAO stackDAO = injector.getInstance(StackDAO.class);
    StackEntity stackEntity = stackDAO.find("HDP", "1.1");
    Assert.assertNotNull(stackEntity);

    final ResourceProvider provider = injector.getInstance(ResourceProviderFactory.class).getRepositoryVersionResourceProvider();
    final RepositoryVersionDAO repositoryVersionDAO = injector.getInstance(RepositoryVersionDAO.class);
    final RepositoryVersionEntity entity = new RepositoryVersionEntity();
    entity.setDisplayName("name");
    entity.setOperatingSystems(jsonStringRedhat6);
    entity.setStack(stackEntity);
    entity.setVersion("1.1.1.1");

    final Request getRequest = PropertyHelper.getReadRequest(RepositoryVersionResourceProvider.REPOSITORY_VERSION_ID_PROPERTY_ID,
        RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_NAME_PROPERTY_ID,
        RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_VERSION_PROPERTY_ID);
    final Predicate predicateStackName = new PredicateBuilder().property(RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_NAME_PROPERTY_ID).equals("HDP").toPredicate();
    final Predicate predicateStackVersion = new PredicateBuilder().property(RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_VERSION_PROPERTY_ID).equals("1.1").toPredicate();
    Assert.assertEquals(0, provider.getResources(getRequest, new AndPredicate(predicateStackName, predicateStackVersion)).size());

    repositoryVersionDAO.create(entity);

    Assert.assertEquals(1, provider.getResources(getRequest, new AndPredicate(predicateStackName, predicateStackVersion)).size());
  }

  @Test
  public void testValidateRepositoryVersion() throws Exception {
    StackDAO stackDAO = injector.getInstance(StackDAO.class);
    StackEntity stackEntity = stackDAO.find("HDP", "1.1");
    Assert.assertNotNull(stackEntity);

    final RepositoryVersionResourceProvider provider = (RepositoryVersionResourceProvider) injector.getInstance(ResourceProviderFactory.class).getRepositoryVersionResourceProvider();

    final RepositoryVersionEntity entity = new RepositoryVersionEntity();
    entity.setDisplayName("name");
    entity.setStack(stackEntity);
    entity.setUpgradePackage("pack1");
    entity.setVersion("1.1");
    entity.setOperatingSystems("[{\"OperatingSystems/os_type\":\"redhat6\",\"repositories\":[{\"Repositories/repo_id\":\"1\",\"Repositories/repo_name\":\"1\",\"Repositories/base_url\":\"http://example.com/repo1\"}]}]");

    // test valid usecases
    provider.validateRepositoryVersion(entity);
    entity.setVersion("1.1-17");
    provider.validateRepositoryVersion(entity);
    entity.setVersion("1.1.1.1");
    provider.validateRepositoryVersion(entity);
    entity.setVersion("1.1.343432.2");
    provider.validateRepositoryVersion(entity);
    entity.setVersion("1.1.343432.2-234234324");
    provider.validateRepositoryVersion(entity);

    // test invalid usecases
    entity.setOperatingSystems(jsonStringRedhat7);
    try {
      provider.validateRepositoryVersion(entity);
      Assert.fail("Should throw exception");
    } catch (Exception ex) {
    }

    entity.setOperatingSystems("");
    try {
      provider.validateRepositoryVersion(entity);
      Assert.fail("Should throw exception");
    } catch (Exception ex) {
    }

    entity.setUpgradePackage("pack2");
    try {
      provider.validateRepositoryVersion(entity);
      Assert.fail("Should throw exception");
    } catch (Exception ex) {
    }

    StackEntity bigtop = new StackEntity();
    stackEntity.setStackName("BIGTOP");
    entity.setStack(bigtop);
    try {
      provider.validateRepositoryVersion(entity);
      Assert.fail("Should throw exception");
    } catch (Exception ex) {
    }

    final RepositoryVersionDAO repositoryVersionDAO = injector.getInstance(RepositoryVersionDAO.class);
    entity.setDisplayName("name");
    entity.setStack(stackEntity);
    entity.setUpgradePackage("pack1");
    entity.setVersion("1.1");
    entity.setOperatingSystems("[{\"OperatingSystems/os_type\":\"redhat6\",\"repositories\":[{\"Repositories/repo_id\":\"1\",\"Repositories/repo_name\":\"1\",\"Repositories/base_url\":\"http://example.com/repo1\"}]}]");
    repositoryVersionDAO.create(entity);

    final RepositoryVersionEntity entity2 = new RepositoryVersionEntity();
    entity2.setId(2l);
    entity2.setDisplayName("name2");
    entity2.setStack(stackEntity);
    entity2.setUpgradePackage("pack1");
    entity2.setVersion("1.2");
    entity2.setOperatingSystems("[{\"OperatingSystems/os_type\":\"redhat6\",\"repositories\":[{\"Repositories/repo_id\":\"1\",\"Repositories/repo_name\":\"1\",\"Repositories/base_url\":\"http://example.com/repo1\"}]}]");

    try {
      provider.validateRepositoryVersion(entity2);
      Assert.fail("Should throw exception: Base url http://example.com/repo1 is already defined for another repository version");
    } catch (Exception ex) {
    }

  }

  @Test
  public void testDeleteResources() throws Exception {
    final ResourceProvider provider = injector.getInstance(ResourceProviderFactory.class).getRepositoryVersionResourceProvider();

    final Set<Map<String, Object>> propertySet = new LinkedHashSet<Map<String, Object>>();
    final Map<String, Object> properties = new LinkedHashMap<String, Object>();
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_DISPLAY_NAME_PROPERTY_ID, "name");
    properties.put(RepositoryVersionResourceProvider.SUBRESOURCE_OPERATING_SYSTEMS_PROPERTY_ID, new Gson().fromJson("[{\"OperatingSystems/os_type\":\"redhat6\",\"repositories\":[{\"Repositories/repo_id\":\"1\",\"Repositories/repo_name\":\"1\",\"Repositories/base_url\":\"1\"}]}]", Object.class));
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_NAME_PROPERTY_ID, "HDP");
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_UPGRADE_PACK_PROPERTY_ID, "pack1");
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_VERSION_PROPERTY_ID, "1.1");
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_REPOSITORY_VERSION_PROPERTY_ID, "1.1.1.2");
    propertySet.add(properties);

    final Predicate predicateStackName = new PredicateBuilder().property(RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_NAME_PROPERTY_ID).equals("HDP").toPredicate();
    final Predicate predicateStackVersion = new PredicateBuilder().property(RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_VERSION_PROPERTY_ID).equals("1.1").toPredicate();
    final Request getRequest = PropertyHelper.getReadRequest(RepositoryVersionResourceProvider.REPOSITORY_VERSION_DISPLAY_NAME_PROPERTY_ID);
    Assert.assertEquals(0, provider.getResources(getRequest, new AndPredicate(predicateStackName, predicateStackVersion)).size());

    final Request createRequest = PropertyHelper.getCreateRequest(propertySet, null);
    provider.createResources(createRequest);

    Assert.assertEquals(1, provider.getResources(getRequest, new AndPredicate(predicateStackName, predicateStackVersion)).size());

    final Predicate predicate = new PredicateBuilder().property(RepositoryVersionResourceProvider.REPOSITORY_VERSION_ID_PROPERTY_ID).equals("1").toPredicate();
    provider.deleteResources(predicate);

    Assert.assertEquals(0, provider.getResources(getRequest, new AndPredicate(predicateStackName, predicateStackVersion)).size());
  }

  @Test
  public void testUpdateResources() throws Exception {
    final ResourceProvider provider = injector.getInstance(ResourceProviderFactory.class).getRepositoryVersionResourceProvider();

    final Set<Map<String, Object>> propertySet = new LinkedHashSet<Map<String, Object>>();
    final Map<String, Object> properties = new LinkedHashMap<String, Object>();
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_DISPLAY_NAME_PROPERTY_ID, "name");
    properties.put(RepositoryVersionResourceProvider.SUBRESOURCE_OPERATING_SYSTEMS_PROPERTY_ID, new Gson().fromJson("[{\"OperatingSystems/os_type\":\"redhat6\",\"repositories\":[{\"Repositories/repo_id\":\"1\",\"Repositories/repo_name\":\"1\",\"Repositories/base_url\":\"http://example.com/repo1\"}]}]", Object.class));
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_NAME_PROPERTY_ID, "HDP");
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_UPGRADE_PACK_PROPERTY_ID, "pack1");
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_VERSION_PROPERTY_ID, "1.1");
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_REPOSITORY_VERSION_PROPERTY_ID, "1.1.1.1");
    propertySet.add(properties);

    final Predicate predicateStackName = new PredicateBuilder().property(RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_NAME_PROPERTY_ID).equals("HDP").toPredicate();
    final Predicate predicateStackVersion = new PredicateBuilder().property(RepositoryVersionResourceProvider.REPOSITORY_VERSION_STACK_VERSION_PROPERTY_ID).equals("1.1").toPredicate();
    final Request getRequest = PropertyHelper.getReadRequest(
        RepositoryVersionResourceProvider.REPOSITORY_VERSION_DISPLAY_NAME_PROPERTY_ID,
        RepositoryVersionResourceProvider.SUBRESOURCE_OPERATING_SYSTEMS_PROPERTY_ID,
        RepositoryVersionResourceProvider.REPOSITORY_VERSION_UPGRADE_PACK_PROPERTY_ID);
    Assert.assertEquals(0, provider.getResources(getRequest, new AndPredicate(predicateStackName, predicateStackVersion)).size());

    final Request createRequest = PropertyHelper.getCreateRequest(propertySet, null);
    provider.createResources(createRequest);

    Assert.assertEquals(1, provider.getResources(getRequest, new AndPredicate(predicateStackName, predicateStackVersion)).size());
    Assert.assertEquals("name", provider.getResources(getRequest, new AndPredicate(predicateStackName, predicateStackVersion)).iterator().next().getPropertyValue(RepositoryVersionResourceProvider.REPOSITORY_VERSION_DISPLAY_NAME_PROPERTY_ID));

    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_UPGRADE_PACK_PROPERTY_ID, null);

    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_ID_PROPERTY_ID, "1");
    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_DISPLAY_NAME_PROPERTY_ID, "name2");
    final Request updateRequest = PropertyHelper.getUpdateRequest(properties, null);
    provider.updateResources(updateRequest, new AndPredicate(predicateStackName, predicateStackVersion));

    Assert.assertEquals("name2", provider.getResources(getRequest, new AndPredicate(predicateStackName, predicateStackVersion)).iterator().next().getPropertyValue(RepositoryVersionResourceProvider.REPOSITORY_VERSION_DISPLAY_NAME_PROPERTY_ID));

    properties.put(RepositoryVersionResourceProvider.SUBRESOURCE_OPERATING_SYSTEMS_PROPERTY_ID, new Gson().fromJson("[{\"OperatingSystems/os_type\":\"redhat6\",\"repositories\":[{\"Repositories/repo_id\":\"2\",\"Repositories/repo_name\":\"2\",\"Repositories/base_url\":\"2\"}]}]", Object.class));
    provider.updateResources(updateRequest, new AndPredicate(predicateStackName, predicateStackVersion));

    properties.put(RepositoryVersionResourceProvider.REPOSITORY_VERSION_UPGRADE_PACK_PROPERTY_ID, "pack2");
    try {
      provider.updateResources(updateRequest, new AndPredicate(predicateStackName, predicateStackVersion));
      Assert.fail("Update of upgrade pack should not be allowed when repo version is installed on any cluster");
    } catch (Exception ex) {
    }
  }

  @Test
  public void testVersionInStack(){
    StackId sid = new StackId("HDP-2.3");
    StackId sid2 = new StackId("HDP-2.3.NEW");
    Assert.assertEquals(true, RepositoryVersionEntity.isVersionInStack(sid, "2.3"));
    Assert.assertEquals(true, RepositoryVersionEntity.isVersionInStack(sid2, "2.3"));

    Assert.assertEquals(true, RepositoryVersionEntity.isVersionInStack(sid, "2.3.1"));
    Assert.assertEquals(true, RepositoryVersionEntity.isVersionInStack(sid2, "2.3.1"));

    Assert.assertEquals(true, RepositoryVersionEntity.isVersionInStack(sid, "2.3.2.0-2300"));
    Assert.assertEquals(true, RepositoryVersionEntity.isVersionInStack(sid2, "2.3.2.1-3562"));

    Assert.assertEquals(false, RepositoryVersionEntity.isVersionInStack(sid, "2.4.2.0-2300"));
    Assert.assertEquals(false, RepositoryVersionEntity.isVersionInStack(sid2, "2.1"));
  }

  @After
  public void after() {
    injector.getInstance(PersistService.class).stop();
    injector = null;
  }
}
