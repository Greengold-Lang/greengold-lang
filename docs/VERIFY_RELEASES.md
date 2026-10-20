# Verifying a Greengold release

Every release publishes `SHA256SUMS.txt` (the SHA-256 of each archive and installer) and `SHA256SUMS.txt.sigstore.json`, a
[Sigstore](https://www.sigstore.dev/) bundle that proves the checksum file was produced by this repository's release workflow. There is
no long-lived signing key to steal or lose: the signature is bound to the workflow's identity and recorded in a public transparency log.
GitHub also stores a build-provenance attestation for each file.

**Status: configured, not yet run.** `.github/workflows/release.yml` has the signing steps, but no tagged release has been made with them
yet, so the commands below have not been tried against a real bundle. The first signed release will confirm or correct this page.

```bash
# 1. the checksum file is the one this repository's release workflow signed
cosign verify-blob SHA256SUMS.txt \
  --bundle SHA256SUMS.txt.sigstore.json \
  --certificate-identity-regexp '^https://github.com/<owner>/<repo>/\.github/workflows/release\.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

# 2. the archive you downloaded is listed in it
sha256sum --check --ignore-missing SHA256SUMS.txt

# 3. (alternative) GitHub's attestation for one file
gh attestation verify gg-linux-x64.tar.gz --repo <owner>/<repo>
```

Replace `<owner>/<repo>` with the repository you downloaded from. `gg update` downloads over HTTPS and compares the
checksum with `SHA256SUMS.txt`; it does not check the Sigstore signature yet, so for a high-assurance install verify by hand as above.
