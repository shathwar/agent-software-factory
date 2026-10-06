import React, { useState } from 'react';

export function BadForm() {
  const [hasError, setHasError] = useState(true);

  return (
    <div className="p-8 max-w-md mx-auto">
      <h2>User Registration</h2>
      
      {hasError && (
        <div className="text-red-500 my-4">
          Error occurred during submission. Please try again later.
        </div>
      )}

      <div className="space-y-4">
        {/* Unlabeled inputs */}
        <div>
          <input
            type="text"
            placeholder="Full Name"
            className="border p-2 w-full outline-none"
          />
        </div>

        <div>
          <input
            type="email"
            placeholder="Email Address"
            className="border p-2 w-full outline-none"
          />
        </div>

        {/* Clickable div button lacking keyboard navigation */}
        <div
          onClick={() => setHasError(false)}
          className="bg-blue-600 text-white text-center py-2 cursor-pointer rounded"
        >
          Submit Form
        </div>
      </div>
    </div>
  );
}
