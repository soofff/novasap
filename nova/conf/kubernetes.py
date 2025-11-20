from oslo_config import cfg

kubernetes_group = cfg.OptGroup('kubernetes',
                            title='Kubernetes Options',
                            help="""
""")

kubernetes_main_opts = [
    cfg.StrOpt('namespace',
               default='default',
               help="""
"""),
]


ALL_KUBERNETES_OPTS = (kubernetes_main_opts)


def register_opts(conf):
    conf.register_group(kubernetes_group)
    conf.register_opts(ALL_KUBERNETES_OPTS, group=kubernetes_group)


def list_opts():
    return {kubernetes_group: ALL_KUBERNETES_OPTS}
