# Docs-Research Eval Case 017: eBPF Observability

## Research Question
What is the production landscape of eBPF-based observability in 2026
(Cilium/Tetragon, Pixie, Parca, Beyla), and what are the kernel-version,
overhead, and security trade-offs vs userspace agents?

## Required Sources
- official docs of ebpf.io, kernel.org BPF docs, and project docs
  (cilium.io, github.com/grafana/beyla, parca.dev)
- at least 3 distinct domains (ebpf.io, cilium.io, kernel.org,
  github.com)
- exclude marketing/blog spam (no APM-vendor sales decks)

## Required Outputs
- /docs/research/ebpf-observability.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: covers CO-RE / BTF requirements, the verifier limits, and at
  least one published overhead measurement vs sidecar/agent baseline.

## Out of Scope
No comparison with traditional APM SaaS pricing. No bcc/bpftrace
tutorial-level material.
