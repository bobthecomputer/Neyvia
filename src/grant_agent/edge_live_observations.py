"""Campaign-local native observations; retained receipt bytes cannot admit cases."""
from __future__ import annotations
import uuid
from urllib.parse import urlsplit
from .proof_ports import c7_worker_ports

class LiveObservations:
    def __init__(self):
        self._cases={}
        self._witnesses={}

    def record(self, contract, category, row, reader, runtime_guard):
        token=self.capture(contract,category,reader,runtime_guard)
        self.admit(contract,category,row,token)

    def capture(self,contract,category,reader,runtime_guard):
        from .edge_contracts import invariant_digest
        if not callable(reader) or not callable(runtime_guard) or runtime_guard() is not True:
            raise ValueError('No live owned native observer')
        observation=reader()
        url=urlsplit(observation.get('url',''))
        if (observation.get('readyState')!='complete' or not observation.get('revision')
                or not (observation.get('elements') or observation.get('text')) or not observation.get('tabId')
                or url.scheme!='http' or url.hostname!='127.0.0.1' or url.port not in c7_worker_ports()):
            raise ValueError('Native observation is unavailable or incomplete')
        if runtime_guard() is not True: raise ValueError('Native observer disconnected during observation')
        nonce=uuid.uuid4().hex
        self._witnesses[nonce]=(contract['id'],category,invariant_digest(contract),
            {'tabId':observation['tabId'],'revision':observation['revision'],'url':observation['url']})
        return nonce

    def admit(self,contract,category,row,nonce):
        from .edge_contracts import invariant_digest
        if row['status']!='passed' or row.get('proofScope')!='rendered' or row['contracts']!=[contract['id']] or row['category']!=category:
            raise ValueError('Live observation requires one exact passing rendered case')
        witness=self._witnesses.get(nonce)
        if not witness or witness[:3]!=(contract['id'],category,invariant_digest(contract)):
            raise ValueError('No exact campaign-local native witness for this completed case')
        self._witnesses.pop(nonce)
        row['liveObservationNonce']=nonce
        row['liveObservation']=witness[3]
        self._cases[row['id']]=(nonce,contract['id'],category,invariant_digest(contract))

    def __call__(self,contract,category,row):
        from .edge_contracts import invariant_digest
        return self._cases.get(row['id'])==(row.get('liveObservationNonce'),contract['id'],category,invariant_digest(contract))
