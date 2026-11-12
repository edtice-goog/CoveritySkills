"""One side of a run (base or head) and the per-language Coverity flags."""

# Language -> the flag cov-import-results takes for it, and the extra flags cov-find-function needs.
LANG_FLAGS = {"c": {"import": "--cpp", "find": []}, "java": {"import": "--java", "find": ["--java"]}}


class Version:
    """One side of a run: its idir, model dump, commit, build roots and coverage files."""

    def __init__(self, ds, label, idir, dump, sha, capture_root, coverage_root, version, files):
        self.ds, self.label, self.idir, self.dump, self.sha = ds, label, idir, dump, sha
        self.capture_root, self.coverage_root, self.version, self.files = capture_root, coverage_root, version, files
        self.ta_idir = f"{ds.work}/ta-idirs/{label}"     # the idir with Test Advisor's issues imported
        self.export_root = f"{ds.work}/src/{label}"      # the head's sources exported from git, for the issues
