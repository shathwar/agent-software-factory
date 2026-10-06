import React from 'react';

export function MobileBroken() {
  return (
    <div className="w-[1280px] p-12 bg-slate-50">
      <h1 className="text-3xl font-bold">Billing & Invoicing History</h1>
      <p className="mt-4 text-xs max-w-[1200px] leading-tight text-slate-500">
        Review your complete enterprise consumption metrics across all interconnected cloud availability zones, transit gateways, virtual network interfaces, and regional storage buckets spanning our global multi-cloud delivery topology over the preceding twenty-four billing cycles with itemized breakdown.
      </p>

      {/* Rigid unscrollable horizontal table layout with tiny touch targets */}
      <div className="flex gap-8 mt-8 border-b pb-4">
        <div className="w-64 font-semibold text-sm">Invoice #INV-2026-001</div>
        <div className="w-48 text-sm">Oct 01, 2026</div>
        <div className="w-32 text-sm font-mono">$14,280.00</div>
        <div className="flex gap-2">
          {/* Sub-minimum 14x14px touch target button */}
          <button
            type="button"
            className="w-3.5 h-3.5 text-[9px] bg-slate-200 hover:bg-slate-300 rounded flex items-center justify-center p-0"
            title="Download PDF"
          >
            ↓
          </button>
          <button
            type="button"
            className="w-3.5 h-3.5 text-[9px] bg-slate-200 hover:bg-slate-300 rounded flex items-center justify-center p-0"
            title="Print receipt"
          >
            ⎙
          </button>
        </div>
      </div>
    </div>
  );
}
