export type PolicyDecisionStatus = "ALLOWED" | "DENIED" | "REQUIRES_APPROVAL";

export interface PolicyRuleSet {
  skill?: string;
  risk?: "low" | "medium" | "high" | "critical";
  allowed?: {
    filesystem?: "workspace" | "read_only" | "scratch" | "none";
    git?: "read/write" | "read" | "none";
    network?: "none" | "internal" | "external";
    tools?: string[];
    commands?: string[];
  };
  requires_approval?: {
    commit?: boolean;
    pull_request?: boolean;
    deployment?: boolean;
    [key: string]: boolean | undefined;
  };
  forbidden?: {
    production?: boolean;
    credentials?: boolean;
    force_push?: boolean;
    paths?: string[];
    [key: string]: boolean | string[] | undefined;
  };
}

export interface PolicyDecision {
  status: PolicyDecisionStatus;
  reason: string;
}

export class PolicyEngine {
  readonly policy: PolicyRuleSet;
  constructor(policy: PolicyRuleSet = {}) {
    this.policy = policy;
  }

  evaluateTool(toolName: string): PolicyDecision {
    const allowed = this.policy.allowed?.tools ?? ["*"];
    if (allowed.includes("*") || allowed.includes(toolName)) {
      return { status: "ALLOWED", reason: `Tool ${toolName} permitted by policy` };
    }
    return { status: "DENIED", reason: `Tool ${toolName} not permitted in allowed.tools` };
  }

  evaluateAction(action: string, metadata: Record<string, any> = {}): PolicyDecision {
    if (action === "force_push" && this.policy.forbidden?.force_push) {
      return { status: "DENIED", reason: "Force push strictly forbidden by policy" };
    }
    if (action === "production" && this.policy.forbidden?.production) {
      return { status: "DENIED", reason: "Direct production action strictly forbidden by policy" };
    }
    if (this.policy.requires_approval?.[action]) {
      return { status: "REQUIRES_APPROVAL", reason: `Action ${action} requires explicit human approval` };
    }
    return { status: "ALLOWED", reason: `Action ${action} allowed` };
  }
}
