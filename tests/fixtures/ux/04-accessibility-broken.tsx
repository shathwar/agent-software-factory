import React from 'react';

export function AccessibilityBroken() {
  return (
    <div className="bg-white p-8">
      {/* Low contrast text (WCAG contrast failure) */}
      <h1 className="text-gray-300 font-bold text-lg">System Configuration</h1>
      
      {/* Icon button lacking accessible label */}
      <button className="p-2 border rounded outline-none" onClick={() => console.log('refresh')}>
        <svg className="w-5 h-5 text-gray-400" viewBox="0 0 20 20" fill="currentColor">
          <path d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1z" />
        </svg>
      </button>

      {/* Unlabeled form input */}
      <div className="mt-4">
        <input type="text" placeholder="Cluster name" className="border p-2" />
      </div>

      {/* Clickable span lacking keyboard navigation */}
      <div className="mt-6">
        <span
          onClick={() => alert('Confirmed')}
          className="bg-red-500 text-white px-4 py-2 cursor-pointer"
        >
          Decommission Node
        </span>
      </div>
    </div>
  );
}
