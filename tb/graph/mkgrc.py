"""Writes GNU Radio Companion flowgraphs (file format 1) from a compact Python description."""
import yaml


class G:
    def __init__(self, gid):
        self.gid = gid
        self.blocks = []
        self.conns = []
        self._n = 0

    def var(self, name, value, kind='variable', **kw):
        p = dict(value=str(value), comment=kw.pop('comment', ''))
        p.update({k: str(v) for k, v in kw.items()})
        self.blocks.append(dict(name=name, id=kind, parameters=p, states=dict(state='enabled', coordinate=[0, 0], rotation=0)))
        return name

    def b(self, bid, name=None, comment='', state='enabled', **params):
        self._n += 1
        name = name or f'{bid.split("_", 1)[-1]}_{self._n}'
        p = {k: str(v) for k, v in params.items()}
        p['comment'] = comment
        self.blocks.append(dict(name=name, id=bid, parameters=p, states=dict(state=state, coordinate=[0, 0], rotation=0)))
        return name

    def c(self, a, b, pa=0, pb=0):
        self.conns.append([a, str(pa), b, str(pb)])

    def chain(self, *names):
        for x, y in zip(names, names[1:]):
            if isinstance(x, tuple):
                self.c(x[0], y if not isinstance(y, tuple) else y[0], x[1], 0 if not isinstance(y, tuple) else y[1])
            else:
                self.c(x, y if not isinstance(y, tuple) else y[0], 0, 0 if not isinstance(y, tuple) else y[1])

    def write(self, path):
        d = dict(options=dict(parameters=dict(id=self.gid, generate_options='no_gui', output_language='python', title=self.gid),
                              states=dict(state='enabled', coordinate=[0, 0], rotation=0)),
                 blocks=self.blocks, connections=self.conns, metadata=dict(file_format=1))
        with open(path, 'w') as f:
            yaml.safe_dump(d, f, sort_keys=False)
        return path
