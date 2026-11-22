"""Compare the three Lab 02 posting representations on the same corpus."""
from array import array
from dataclasses import dataclass
import json
from pathlib import Path
import pickle
import time
import tracemalloc
from findex.index import build_index


@dataclass(frozen=True)
class PlainPosting:
    doc_id: int
    tf: int


@dataclass(frozen=True, slots=True)
class SlotPosting:
    doc_id: int
    tf: int


def main() -> None:
    ix=build_index(Path('data'))
    result={}
    for kind in ('plain','slots','array'):
        tracemalloc.start()
        start=time.perf_counter()
        if kind=='array':
            obj={t:array('I',(x for p in posts for x in (p.doc_id,p.tf))) for t,posts in ix.postings.items()}
        else:
            cls=PlainPosting if kind=='plain' else SlotPosting
            obj={t:[cls(p.doc_id,p.tf) for p in posts] for t,posts in ix.postings.items()}
        _,peak=tracemalloc.get_traced_memory()
        tracemalloc.stop()
        payload=pickle.dumps(obj,protocol=pickle.HIGHEST_PROTOCOL)
        load_started=time.perf_counter()
        pickle.loads(payload)
        result[kind]={'build_peak_bytes':peak,'serialized_bytes':len(payload),'load_s':time.perf_counter()-load_started}
    Path('docs/posting-memory.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    main()
