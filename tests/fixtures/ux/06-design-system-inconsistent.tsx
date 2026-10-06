import React from 'react';

export function DesignSystemInconsistent() {
  return (
    <div className="p-[17px] bg-[#fdf8f4]">
      <h1 className="text-[23px] font-bold text-[#7a3b12]">Inconsistent Design Tokens</h1>
      <p className="mt-[11px] text-[13.5px] text-[#4b5563]">
        This component bypasses the project design tokens by using hardcoded arbitrary values and rogue hex colors.
      </p>

      <div className="mt-[19px] p-[13px] rounded-[7px] border border-[#e2418a] bg-[#fff0f6]">
        <h2 className="text-[15px] font-semibold text-[#e2418a]">Arbitrary Alert Box</h2>
        <div className="mt-[15px] flex gap-[9px]">
          <button
            type="button"
            className="px-[19px] py-[7px] bg-[#194a73] text-white rounded-none text-[12px]"
          >
            Square Button
          </button>
          <button
            type="button"
            className="px-[14px] py-[6px] bg-[#e2418a] text-white rounded-full text-[12px]"
          >
            Pill Button
          </button>
          <button
            type="button"
            className="px-[11px] py-[9px] bg-[#7a3b12] text-white rounded-[7px] text-[12px]"
          >
            Custom Radius
          </button>
        </div>
      </div>
    </div>
  );
}
