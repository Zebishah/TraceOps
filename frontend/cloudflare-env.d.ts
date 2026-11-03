declare namespace Cloudflare {
  interface Env {
    OPSPILOT_BACKEND_URL?: string;
    DB?: D1Database;
    BUCKET?: R2Bucket;
  }
}
