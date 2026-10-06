import React from 'react';

export function AiSlopLandingPage() {
  return (
    <div className="min-h-screen bg-slate-950 text-white relative overflow-hidden flex flex-col items-center">
      {/* Background purple glow soup */}
      <div className="absolute inset-0 bg-gradient-to-br from-purple-900/40 via-indigo-900/20 to-pink-900/30 blur-3xl -z-10" />

      {/* Floating badge */}
      <div className="mt-20 inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-purple-500/30 bg-purple-500/10 text-purple-300 text-xs font-semibold backdrop-blur-md">
        <span>✨ The Future of Autonomous Neural Intelligence</span>
      </div>

      {/* Generic centered hero */}
      <div className="max-w-4xl text-center px-6 mt-8">
        <h1 className="text-5xl md:text-7xl font-extrabold tracking-tight bg-gradient-to-r from-purple-400 via-pink-400 to-indigo-400 bg-clip-text text-transparent">
          Supercharge Everything With Next-Gen AI
        </h1>
        <p className="mt-6 text-lg text-purple-200/60 max-w-2xl mx-auto">
          Unlock synergistic exponential paradigms with our hyper-intelligent multi-modal vector engine. Seamlessly augment your workflow today.
        </p>

        <div className="mt-10 flex justify-center gap-4">
          <button
            type="button"
            className="px-8 py-4 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 text-white font-semibold shadow-[0_0_30px_rgba(168,85,247,0.7)] hover:shadow-[0_0_45px_rgba(168,85,247,0.9)] border border-purple-400/50 transition duration-300"
          >
            Claim Free Access
          </button>
        </div>
      </div>

      {/* Symmetrical 3-card glassmorphism soup */}
      <div className="max-w-6xl w-full px-6 grid grid-cols-1 md:grid-cols-3 gap-8 mt-24 pb-20">
        <div className="p-8 rounded-2xl bg-white/5 border border-white/10 backdrop-blur-lg hover:border-purple-500/50 transition">
          <div className="w-12 h-12 rounded-xl bg-purple-600/20 border border-purple-500/30 flex items-center justify-center text-purple-400 text-xl">
            ⚡
          </div>
          <h3 className="text-xl font-bold mt-4">Ultra Velocity</h3>
          <p className="mt-2 text-sm text-slate-400">Transform raw compute into effortless productivity in real-time.</p>
        </div>

        <div className="p-8 rounded-2xl bg-white/5 border border-white/10 backdrop-blur-lg hover:border-purple-500/50 transition">
          <div className="w-12 h-12 rounded-xl bg-purple-600/20 border border-purple-500/30 flex items-center justify-center text-purple-400 text-xl">
            🔮
          </div>
          <h3 className="text-xl font-bold mt-4">Predictive Insight</h3>
          <p className="mt-2 text-sm text-slate-400">Deep neural foresight anticipates your next business move seamlessly.</p>
        </div>

        <div className="p-8 rounded-2xl bg-white/5 border border-white/10 backdrop-blur-lg hover:border-purple-500/50 transition">
          <div className="w-12 h-12 rounded-xl bg-purple-600/20 border border-purple-500/30 flex items-center justify-center text-purple-400 text-xl">
            🛡️
          </div>
          <h3 className="text-xl font-bold mt-4">Quantum Security</h3>
          <p className="mt-2 text-sm text-slate-400">Zero-trust cryptographic protocols safeguarding your proprietary telemetry.</p>
        </div>
      </div>
    </div>
  );
}
