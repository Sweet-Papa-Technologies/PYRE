// Canonical outbound links + product copy for the PyrePress site.
// PyrePress is the news/blog section of PYRE — a Python framework for the
// Internet Computer, by Sweet Papa Technologies. One source of truth so the
// header, footer, hero and product band never drift.

export const SITE = {
  // The framework this site is built with (and about).
  pyre: {
    name: 'PYRE',
    tagline: 'Python on the Internet Computer',
    pitch:
      'Write recognizable Python — Flask-style routes, a data layer, outbound HTTP — and run it on the Internet Computer. No Rust, no Motoko, no Candid.',
    install: 'pip install pyre-icp',
    github: 'https://github.com/Sweet-Papa-Technologies/PYRE',
    docs: 'https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/README.md',
    quickstart:
      'https://github.com/Sweet-Papa-Technologies/PYRE/blob/main/docs/quickstart.md',
    pypi: 'https://pypi.org/project/pyre-icp/',
  },
  // The company behind PYRE.
  company: {
    name: 'Sweet Papa Technologies',
    url: 'https://sweetpapatechnologies.com',
  },
  // Platform this runs on.
  ic: {
    name: 'Internet Computer',
    url: 'https://internetcomputer.org',
  },
} as const

// Feature highlights for the "Built with PYRE" product band.
export const PYRE_FEATURES = [
  {
    icon: 'pi-verified',
    title: 'Certified responses',
    body: 'Clients cryptographically verify your API against the network root of trust — not "trust the server."',
  },
  {
    icon: 'pi-key',
    title: 'Threshold-signed',
    body: 'The subnet signs cooperatively. There is no private key anywhere to steal — sign JWTs with no secret to leak.',
  },
  {
    icon: 'pi-bolt',
    title: 'Just Python',
    body: 'Flask-shaped routes, pip install, a dev server. The consensus and certification stay out of your way.',
  },
] as const
