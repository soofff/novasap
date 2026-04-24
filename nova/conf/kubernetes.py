from oslo_config import cfg

kubernetes_group = cfg.OptGroup('kubernetes',
                            title='Kubernetes Options',
                            help="""
Options for the Kubernetes compute driver that exports Nova instance
lifecycle operations to Kubernetes CRDs.
""")

kubernetes_main_opts = [
    cfg.StrOpt('namespace',
               default='default',
               help="""
The Kubernetes namespace in which to create CRD resources.
Instance and Port CRDs will be created in this namespace.
"""),

    cfg.BoolOpt('apply_crds',
               default=False,
               help="""
Deploy the OpenStack CRDs to the Kubernetes cluster if they do not already exist.
This requires that the user configured to access the cluster has sufficient
privileges to create CustomResourceDefinitions.
The CRDs created are: instances.nova.openstack.org and ports.nova.openstack.org
"""),

    cfg.StrOpt('config',
               default=None,
               help="""
The path to the kubeconfig file to use to access the Kubernetes cluster.
If not specified, the in-cluster configuration will be used when
running inside a Kubernetes Pod, or the default kubeconfig file location
will be used when running outside of a cluster.
"""),

    cfg.StrOpt('api_group',
               default='nova.openstack.org',
               help="""
The Kubernetes API group for CRDs.
This should match the monsoon4 nova reimplementation for controller compatibility.
Default: nova.openstack.org
"""),

    cfg.BoolOpt('create_port_crds',
                default=True,
                help="""
Create separate Port CRDs for network interfaces.
When enabled, each network interface gets its own Port CRD resource,
allowing the controller to manage network binding independently.
"""),
]


ALL_KUBERNETES_OPTS = (kubernetes_main_opts)


def register_opts(conf):
    conf.register_group(kubernetes_group)
    conf.register_opts(ALL_KUBERNETES_OPTS, group=kubernetes_group)


def list_opts():
    return {kubernetes_group: ALL_KUBERNETES_OPTS}
