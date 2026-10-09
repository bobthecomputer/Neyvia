"""Owned LAYA service: transformer by default, calibrated CPU head for browser calls."""
from pathlib import Path
import importlib.util
import json
from .laya_client.fast_cpu import FastCPU


def main():
    """Keep frozen regression calls independent of the live browser head."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--database', required=True)
    parser.add_argument('--question-sets', required=True)
    parser.add_argument('--memory-capacity', type=int, default=4096)
    parser.add_argument('--model', type=Path)
    parser.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    parser.add_argument('--calibration', type=Path)
    args = parser.parse_args()
    adapter = FastCPU(args.project)
    from laya_system1.service import Engine, create_server
    adapter.runtime.identity = adapter.identity
    runtime = adapter.runtime
    if args.model:
        # FastCPU imports its identity-bound project package. Load the exact
        # repository transformer implementation without changing that package.
        path = Path(__file__).resolve().parents[2] / 'tools/laya/laya_system1/runtime.py'
        spec = importlib.util.spec_from_file_location('neyvia_transformer_runtime', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        runtime = module.Runtime(args.model, device=args.device, calibration=args.calibration)

    class AppEngine(Engine):
        def decide(self, request, use_memory=True):
            learned = request.get('set') == 'neyvia.learned@2'
            # Browser action/advisory calibration is for the unchanged frozen base,
            # never for a memory-modified distribution. Learned hooks are separate.
            browser = (request.get('client') == 't20-laya-hook' and
                       (request.get('set') in (None, 'neyvia.cl-state@1') or
                        (learned and request.get('questions') == ['page_done']))) or (
                       request.get('client') in {'neyvia-page_done', 'neyvia-outcome-binding'} and learned and
                       request.get('questions') == ['page_done'])
            # Identity, fingerprints, cache keys and durable decision records all
            # follow the selected runtime. Serialize selection with inference.
            with self.lock:
                original = self.runtime
                try:
                    if browser:
                        self.runtime = adapter.runtime
                    response = super().decide(request, use_memory=use_memory and
                        (request.get('client') != 't20-laya-hook' or learned))
                    if learned:
                        for answer in response['answers'].values():
                            if answer.get('source') == 'laya':
                                answer['policy'] = 'escalate'  # requires verified episodes
                    return response
                finally:
                    self.runtime = original

        def health(self):
            return {**super().health(), 'browser_identity': adapter.identity}

    engine = AppEngine(runtime, args.database, args.question_sets, args.memory_capacity)
    server = create_server(engine, port=args.port)
    print(json.dumps({'listening': args.port, 'identity': runtime.identity,
                      'browser_identity': adapter.identity}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        engine.close()


if __name__ == '__main__':
    main()
