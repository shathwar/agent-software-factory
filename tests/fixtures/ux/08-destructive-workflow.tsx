import React, { useState } from 'react';

export function DestructiveWorkflow() {
  const [status, setStatus] = useState(null);

  const handleDelete = () => {
    // Immediate destructive deletion without confirmation
    setStatus('deleted');
  };

  return (
    <div className="p-8 max-w-lg border border-red-200 rounded-lg bg-red-50/20">
      <h2 className="text-xl font-bold text-red-600">Danger Zone</h2>
      <p className="mt-2 text-sm text-gray-600">
        Deleting your organization will immediately terminate all active clusters, wipe databases, and revoke API access.
      </p>

      {status === 'deleted' && (
        <div className="mt-4 p-3 bg-red-100 text-red-700 text-sm rounded">
          Organization deleted.
        </div>
      )}

      {/* Immediate destructive action with clickable div and no confirmation modal */}
      <div className="mt-6">
        <div
          onClick={handleDelete}
          className="inline-block px-4 py-2 bg-red-600 text-white rounded cursor-pointer text-sm font-semibold"
        >
          Delete Organization Immediately
        </div>
      </div>
    </div>
  );
}
