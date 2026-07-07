export type LegalNoticeComponent = {
  name: string;
  version: string;
  license: string;
  ecosystem: "python" | "npm" | string;
  purl?: string;
};

export type LegalNoticesFile = {
  generatedAt: string;
  sbomVersion: string;
  scope: string[];
  componentCount: number;
  components: LegalNoticeComponent[];
};
