//! MemoryBackend trait for all storage backends.

use openjarvis_core::{AURAError, RetrievalResult};
use serde_json::Value;

pub trait MemoryBackend: Send + Sync {
    fn backend_id(&self) -> &str;
    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, AURAError>;
    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, AURAError>;
    fn delete(&self, doc_id: &str) -> Result<bool, AURAError>;
    fn clear(&self) -> Result<(), AURAError>;
    fn count(&self) -> Result<usize, AURAError>;
}
