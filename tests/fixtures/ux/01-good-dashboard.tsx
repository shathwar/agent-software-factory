import React from 'react';

export function GoodDashboard() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <header className="border-b border-slate-800 px-6 py-4 flex items-center justify-between">
        <h1 className="text-xl font-bold tracking-tight">Cloud Metrics Console</h1>
        <div className="flex items-center gap-4">
          <label htmlFor="search-input" className="sr-only">Search resources</label>
          <input
            id="search-input"
            type="search"
            placeholder="Search resources..."
            className="bg-slate-900 border border-slate-700 rounded-md px-3 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          />
          <button
            type="button"
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-md text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
          >
            Create Cluster
          </button>
        </div>
      </header>

      <main className="p-6 grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
          <h2 className="text-sm font-medium text-slate-400">Total CPU Utilization</h2>
          <p className="text-3xl font-bold mt-2">42.8%</p>
          <p className="text-xs text-emerald-400 mt-1">↑ 2.4% from last hour</p>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
          <h2 className="text-sm font-medium text-slate-400">Memory Pressure</h2>
          <p className="text-3xl font-bold mt-2">61.2%</p>
          <p className="text-xs text-slate-400 mt-1">Normal operating bounds</p>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
          <h2 className="text-sm font-medium text-slate-400">Active Node Replicas</h2>
          <p className="text-3xl font-bold mt-2">18 / 20</p>
          <p className="text-xs text-emerald-400 mt-1">Healthy cluster quorum</p>
        </div>
      </main>
    </div>
  );
}
