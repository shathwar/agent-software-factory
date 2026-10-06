import React, { useState } from 'react';

export function ComplexDataTable({ data = [] }) {
  const [selectedId, setSelectedId] = useState(null);

  return (
    <div className="p-6 bg-white rounded-lg shadow">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-xl font-bold">Deployments</h2>
        <span className="text-sm text-gray-500">Total: {data.length}</span>
      </div>

      <table className="min-w-full divide-y divide-gray-200">
        <thead>
          <tr>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Service</th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Environment</th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {data.map((row) => (
            <tr
              key={row.id}
              onClick={() => setSelectedId(row.id)}
              className="cursor-pointer hover:bg-gray-50"
            >
              <td className="px-6 py-4 text-sm font-mono">{row.id}</td>
              <td className="px-6 py-4 text-sm font-medium">{row.service}</td>
              <td className="px-6 py-4 text-sm">{row.env}</td>
              <td className="px-6 py-4 text-sm">{row.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
