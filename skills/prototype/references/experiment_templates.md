# Experiment Templates & Benchmark Harnesses

Reusable harnesses and patterns for answering empirical engineering questions in isolated scratch environments.

---

## 1. High-Resolution Latency Micro-Benchmark

Measures execution time distributions (p50, p95, p99, max) with warm-up passes and memory sampling.

### Node.js / TypeScript Template (`.scratch/bench_latency.mjs`)

```javascript
import { performance } from 'node:perf_hooks';

async function targetOperation(i) {
  // Replace with the operation under test
  return Math.sqrt(i) * Math.sin(i);
}

async function runBenchmark({ warmups = 1000, iterations = 10000 }) {
  console.log(`[Bench] Warming up (${warmups} iterations)...`);
  for (let i = 0; i < warmups; i++) {
    await targetOperation(i);
  }

  const initialMemory = process.memoryUsage().heapUsed;
  const timings = new Float64Array(iterations);

  console.log(`[Bench] Measuring (${iterations} iterations)...`);
  const totalStart = performance.now();

  for (let i = 0; i < iterations; i++) {
    const start = performance.now();
    await targetOperation(i);
    timings[i] = performance.now() - start;
  }

  const totalDuration = performance.now() - totalStart;
  const finalMemory = process.memoryUsage().heapUsed;

  timings.sort();
  const p50 = timings[Math.floor(iterations * 0.50)];
  const p95 = timings[Math.floor(iterations * 0.95)];
  const p99 = timings[Math.floor(iterations * 0.99)];
  const max = timings[iterations - 1];
  const rps = (iterations / (totalDuration / 1000)).toFixed(0);

  console.log('\n--- Benchmark Results ---');
  console.log(`Total Time:     ${totalDuration.toFixed(2)} ms`);
  console.log(`Throughput:     ${rps} ops/sec`);
  console.log(`Latency p50:    ${p50.toFixed(4)} ms`);
  console.log(`Latency p95:    ${p95.toFixed(4)} ms`);
  console.log(`Latency p99:    ${p99.toFixed(4)} ms`);
  console.log(`Latency max:    ${max.toFixed(4)} ms`);
  console.log(`Heap Delta:     ${((finalMemory - initialMemory) / 1024 / 1024).toFixed(2)} MB`);
}

runBenchmark({ warmups: 1000, iterations: 20000 });
```

### Python Template (`.scratch/bench_latency.py`)

```python
import time
import statistics
import tracemalloc

def target_operation(i: int):
    # Replace with the operation under test
    return sum(x * x for x in range(i % 100))

def run_benchmark(warmups: int = 1000, iterations: int = 20000):
    print(f"[Bench] Warming up ({warmups} iterations)...")
    for i in range(warmups):
        target_operation(i)

    tracemalloc.start()
    timings = []

    print(f"[Bench] Measuring ({iterations} iterations)...")
    total_start = time.perf_counter()

    for i in range(iterations):
        start = time.perf_counter()
        target_operation(i)
        timings.append((time.perf_counter() - start) * 1000.0) # convert to ms

    total_duration = (time.perf_counter() - total_start) * 1000.0
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    timings.sort()
    p50 = statistics.median(timings)
    p95 = timings[int(iterations * 0.95)]
    p99 = timings[int(iterations * 0.99)]
    max_lat = timings[-1]
    rps = iterations / (total_duration / 1000.0)

    print("\n--- Benchmark Results ---")
    print(f"Total Time:     {total_duration:.2f} ms")
    print(f"Throughput:     {rps:.0f} ops/sec")
    print(f"Latency p50:    {p50:.4f} ms")
    print(f"Latency p95:    {p95:.4f} ms")
    print(f"Latency p99:    {p99:.4f} ms")
    print(f"Latency max:    {max_lat:.4f} ms")
    print(f"Peak Memory:    {peak_mem / 1024 / 1024:.2f} MB")

if __name__ == "__main__":
    run_benchmark()
```

---

## 2. Concurrency Contention & Race Condition Harness

Harness to test lock contention, atomic CAS loops, or database row-lock serialization under high worker concurrency.

### Go Concurrency Spike (`.scratch/concurrency_test.go`)

```go
package main

import (
	"fmt"
	"sync"
	"sync/atomic"
	"time"
)

type SharedResource struct {
	mu        sync.Mutex
	balance   int64
	atomicOps int64
}

func (s *SharedResource) SafeUpdate(delta int64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.balance += delta
	atomic.AddInt64(&s.atomicOps, 1)
}

func main() {
	const workers = 64
	const opsPerWorker = 50000
	resource := &SharedResource{}

	var wg sync.WaitGroup
	wg.Add(workers)

	start := time.Now()

	for w := 0; w < workers; w++ {
		go func(workerID int) {
			defer wg.Done()
			for i := 0; i < opsPerWorker; i++ {
				resource.SafeUpdate(1)
			}
		}(w)
	}

	wg.Wait()
	elapsed := time.Since(start)

	expected := int64(workers * opsPerWorker)
	fmt.Printf("--- Concurrency Benchmark ---\n")
	fmt.Printf("Workers:        %d\n", workers)
	fmt.Printf("Total Ops:      %d\n", expected)
	fmt.Printf("Final Balance:  %d (Expected: %d)\n", resource.balance, expected)
	fmt.Printf("Atomic Ops:     %d\n", atomic.LoadInt64(&resource.atomicOps))
	fmt.Printf("Elapsed Time:   %s\n", elapsed)
	fmt.Printf("Throughput:     %.0f ops/sec\n", float64(expected)/elapsed.Seconds())
}
```

---

## 3. Network Fault Injection & Chaos Mock Server

Simulates real-world networking hazards: random jitter, dropped connections, HTTP 429 rate limits, and partial chunk responses.

### Node.js Chaos Mock Server (`.scratch/chaos_server.mjs`)

```javascript
import http from 'node:http';

const PORT = 9999;
let requestCount = 0;

const server = http.createServer((req, res) => {
  requestCount++;

  // 1. Simulate 10% connection drop / abort
  if (requestCount % 10 === 0) {
    console.log(`[Chaos] Dropping request #${requestCount}`);
    req.destroy();
    return;
  }

  // 2. Simulate 20% Rate Limiting (429)
  if (requestCount % 5 === 0) {
    console.log(`[Chaos] Rate limiting request #${requestCount}`);
    res.writeHead(429, { 'Retry-After': '1', 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Too Many Requests' }));
    return;
  }

  // 3. Simulate variable network latency (50ms - 300ms jitter)
  const delay = 50 + Math.random() * 250;
  setTimeout(() => {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', requestId: requestCount, delayMs: delay.toFixed(1) }));
  }, delay);
});

server.listen(PORT, () => {
  console.log(`Chaos Mock Server listening on http://localhost:${PORT}`);
});
```

---

## 4. Large Stream Memory & Allocation Spike

Verifies whether a streaming library leaks memory or buffers unbounded payloads into RAM.

### Node.js Stream Memory Profiler (`.scratch/stream_profile.mjs`)

```javascript
import { Readable } from 'node:stream';

// Generator producing 100,000 JSON lines (~200MB)
async function* generateLines(count) {
  for (let i = 0; i < count; i++) {
    yield JSON.stringify({ id: i, payload: "x".repeat(2048), ts: Date.now() }) + '\n';
  }
}

async function profileStream() {
  const stream = Readable.from(generateLines(100000));
  let parsedCount = 0;

  const initialRss = process.memoryUsage().rss / 1024 / 1024;
  let sampledPeakRss = initialRss;
  let sampledPeakHeap = process.memoryUsage().heapUsed / 1024 / 1024;

  const sample = () => {
    const mem = process.memoryUsage();
    const rss = mem.rss / 1024 / 1024;
    const heap = mem.heapUsed / 1024 / 1024;
    if (rss > sampledPeakRss) sampledPeakRss = rss;
    if (heap > sampledPeakHeap) sampledPeakHeap = heap;
  };

  const interval = setInterval(sample, 50);

  for await (const chunk of stream) {
    parsedCount++;
    // Sample inline every 5k records so fast streams are never missed before interval fires
    if (parsedCount % 5000 === 0) {
      sample();
      process.stdout.write(`\rProcessed: ${parsedCount} | Sampled RSS: ${sampledPeakRss.toFixed(1)} MB | Heap: ${sampledPeakHeap.toFixed(1)} MB`);
    }
  }

  sample();
  clearInterval(interval);

  // Distinguish sampled peak from OS-level process peak RSS (getrusage)
  const resourceUsage = process.resourceUsage ? process.resourceUsage() : null;
  let osMaxRssMb = null;
  if (resourceUsage && resourceUsage.maxRSS) {
    const isMac = process.platform === 'darwin';
    osMaxRssMb = isMac
      ? resourceUsage.maxRSS / (1024 * 1024)
      : resourceUsage.maxRSS / 1024;
  }

  console.log(`\n\n--- Stream Profile Completed ---`);
  console.log(`Total Records:    ${parsedCount}`);
  console.log(`Initial RSS:      ${initialRss.toFixed(2)} MB`);
  console.log(`Sampled Peak RSS: ${sampledPeakRss.toFixed(2)} MB`);
  console.log(`Sampled Peak Heap:${sampledPeakHeap.toFixed(2)} MB`);
  if (osMaxRssMb !== null) {
    console.log(`OS Peak RSS:      ${osMaxRssMb.toFixed(2)} MB (process peak)`);
  }
}

profileStream();
```

---

## 5. UI / Interaction Feel Spike (Single-File Prototype)

When the ungrillable question is ergonomic or visual (e.g. *"How snappy does search feel with 200ms debounce vs instant filtering?"*), create a single-file HTML artifact.

### Standalone HTML Prototype (`.scratch/ui_feel_spike.html`)

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Debounce Feel Spike</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-gray-100 p-8">
  <div class="max-w-md mx-auto space-y-4">
    <h1 class="text-xl font-bold">Search Latency Simulation</h1>
    <input id="search" type="text" placeholder="Type query..." class="w-full p-2 bg-gray-800 border border-gray-700 rounded text-white">
    <div class="text-xs text-gray-400" id="stats">Keystrokes: 0 | Network Requests: 0</div>
    <ul id="results" class="space-y-1 text-sm text-gray-300"></ul>
  </div>
  <script>
    let keystrokes = 0, requests = 0, timer;
    const input = document.getElementById('search');
    const stats = document.getElementById('stats');
    const results = document.getElementById('results');

    input.addEventListener('input', (e) => {
      keystrokes++;
      clearTimeout(timer);
      timer = setTimeout(() => {
        requests++;
        stats.innerText = `Keystrokes: ${keystrokes} | Network Requests: ${requests}`;
        results.innerHTML = `<li class="text-green-400">Query evaluated at ${new Date().toLocaleTimeString()} for: "${e.target.value}"</li>` + results.innerHTML;
      }, 150); // Test 150ms debounce threshold
    });
  </script>
</body>
</html>
```
