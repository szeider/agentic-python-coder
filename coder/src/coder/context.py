"""Execution context for managing session-scoped resources and configuration."""

import logging
import shutil
from typing import List, Optional
from pathlib import Path
from .kernel import PythonKernel

logger = logging.getLogger(__name__)


class ExecutionContext:
    """Manages the environment for a single agent session.
    
    This class encapsulates all session-specific state including:
    - Working directory
    - Package requirements
    - Kernel lifecycle
    
    Each agent run gets its own context, eliminating global state
    and ensuring proper resource cleanup.
    """
    
    def __init__(self, 
                 working_directory: str, 
                 packages: Optional[List[str]] = None,
                 validate_packages: bool = True):
        """Initialize an execution context.
        
        Args:
            working_directory: Directory for file operations and kernel execution
            packages: List of packages for dynamic dependency injection (e.g., ["pandas>=2.0", "numpy"])
            validate_packages: Whether to validate package specifications
            
        Raises:
            FileNotFoundError: If working directory doesn't exist
            ValueError: If package specifications are invalid
            RuntimeError: If UV is not available but packages are specified
        """
        self.working_directory = Path(working_directory).resolve()
        self.packages = packages or []
        self._kernel: Optional[PythonKernel] = None
        
        # Validate working directory
        if not self.working_directory.exists():
            raise FileNotFoundError(f"Working directory not found: {self.working_directory}")
        if not self.working_directory.is_dir():
            raise ValueError(f"Working directory is not a directory: {self.working_directory}")
            
        # Check UV availability if packages are specified
        if self.packages and not self._check_uv_available():
            raise RuntimeError(
                "UV is required for dynamic package mode but not found. "
                "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
            )
        
        # Validate package specifications
        if validate_packages and self.packages:
            self._validate_packages()
            
        logger.info(
            f"ExecutionContext initialized: cwd={self.working_directory}, "
            f"packages={self.packages}"
        )
    
    def _check_uv_available(self) -> bool:
        """Check if UV is available in the system PATH."""
        return shutil.which('uv') is not None
    
    def _validate_packages(self):
        """Validate package specifications.
        
        Raises:
            ValueError: If any package specification is invalid
        """
        import re
        # Basic validation for package specs
        # Format: package_name[extras][@|==|>=|<=|>|<|!=|~=]version
        pattern = re.compile(
            r'^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?'  # Package name
            r'(\[[a-zA-Z0-9,_-]+\])?'  # Optional extras
            r'([@=!<>~]+[a-zA-Z0-9.*+!,\-_.]+)?$'  # Optional version spec
        )
        
        invalid_packages = []
        for pkg in self.packages:
            if not pattern.match(pkg):
                invalid_packages.append(pkg)
        
        if invalid_packages:
            raise ValueError(
                f"Invalid package specifications: {', '.join(invalid_packages)}. "
                f"Expected format: 'package' or 'package>=version'"
            )
    
    def get_kernel(self) -> PythonKernel:
        """Get or create the kernel for this context.
        
        The kernel is created lazily on first access and reused for
        the lifetime of this context.
        
        Returns:
            The Python kernel for this session
            
        Raises:
            RuntimeError: If kernel fails to start
        """
        if self._kernel is None:
            logger.info("Creating new kernel for context")
            try:
                self._kernel = PythonKernel(
                    cwd=str(self.working_directory),
                    with_packages=self.packages if self.packages else None
                )
                logger.info("Kernel created successfully")
            except Exception as e:
                logger.error(f"Failed to create kernel: {e}")
                raise RuntimeError(f"Failed to start kernel: {e}") from e
                
        return self._kernel
    
    def resolve_path(self, file_path: str) -> Path:
        """Resolve a path relative to the working directory.
        
        Args:
            file_path: Path to resolve (must be relative)
            
        Returns:
            Absolute path within the working directory
            
        Raises:
            ValueError: If path is absolute or escapes working directory
        """
        path = Path(file_path)
        
        # Reject absolute paths
        if path.is_absolute():
            raise ValueError(f"Absolute paths not allowed: {file_path}")
        
        # Resolve relative to working directory
        full_path = (self.working_directory / path).resolve()
        
        # Security check: ensure path is within working directory
        try:
            full_path.relative_to(self.working_directory)
        except ValueError:
            raise ValueError(
                f"Path '{file_path}' escapes working directory. "
                f"This is a security violation."
            )
        
        return full_path
    
    def shutdown(self):
        """Clean up all resources for this context.
        
        This should be called when the agent session ends to ensure
        proper cleanup of the kernel and any other resources.
        """
        logger.info("Shutting down ExecutionContext")
        
        if self._kernel:
            try:
                self._kernel.shutdown()
                logger.info("Kernel shut down successfully")
            except Exception as e:
                logger.error(f"Error shutting down kernel: {e}")
            finally:
                self._kernel = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cleanup."""
        self.shutdown()
        return False
    
    def __repr__(self):
        """String representation for debugging."""
        return (
            f"ExecutionContext(cwd={self.working_directory}, "
            f"packages={self.packages}, kernel={'active' if self._kernel else 'none'})"
        )