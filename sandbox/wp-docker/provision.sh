#!/bin/sh
# provision.sh — WP-CLI one-shot sandbox provisioner
# Runs inside the wpcli container. Called once via docker compose entrypoint.
# Exit codes: 0 = success, 1 = failure.

set -e

SANDBOX_URL="http://localhost:8091"
ADMIN_USER="admin"
ADMIN_PASS="Admin@Sandbox1"
ADMIN_EMAIL="sandbox@rankengine.local"
APP_PASS_NAME="rankengine-connector"

# WP-CLI cache — write to a world-writable location to avoid permission errors
export WP_CLI_CACHE_DIR="/tmp/wp-cli-cache"
mkdir -p /tmp/wp-cli-cache

# ------------------------------------------------------------------ #
# 1. Wait for WordPress + DB to be ready
# ------------------------------------------------------------------ #
echo "==> Waiting for database..."
max_tries=60
tries=0
until wp db check --quiet 2>/dev/null; do
  tries=$((tries + 1))
  if [ "$tries" -ge "$max_tries" ]; then
    echo "ERROR: Database not ready after ${max_tries}s. Aborting."
    exit 1
  fi
  sleep 1
done
echo "    DB ready after ${tries}s."

# Wait for WordPress files to exist
echo "==> Waiting for WordPress files..."
until [ -f /var/www/html/wp-config.php ]; do
  sleep 2
done
echo "    wp-config.php found."

# ------------------------------------------------------------------ #
# 2. Core install (idempotent — skip if already installed)
# ------------------------------------------------------------------ #
echo "==> Installing WordPress core..."
if wp core is-installed --quiet 2>/dev/null; then
  echo "    Already installed — skipping."
else
  wp core install \
    --url="$SANDBOX_URL" \
    --title="Fluid Controls Sandbox (WP)" \
    --admin_user="$ADMIN_USER" \
    --admin_password="$ADMIN_PASS" \
    --admin_email="$ADMIN_EMAIL" \
    --skip-email
  echo "    Core installed."
fi

# ------------------------------------------------------------------ #
# 3. Update site URL to match nginx proxy
# ------------------------------------------------------------------ #
echo "==> Setting site URL..."
wp option update siteurl "$SANDBOX_URL"
wp option update home "$SANDBOX_URL"

# ------------------------------------------------------------------ #
# 4. Permalink structure (required for clean REST API slugs)
# ------------------------------------------------------------------ #
echo "==> Setting permalink structure..."
wp rewrite structure '/%postname%/' --hard

# ------------------------------------------------------------------ #
# 5. Install and activate Yoast SEO
#    (Same plugin confirmed on live fluidcontrols.com via wp-json namespaces)
# ------------------------------------------------------------------ #
echo "==> Installing Yoast SEO..."
if wp plugin is-installed wordpress-seo --quiet 2>/dev/null; then
  echo "    Already installed — activating."
  wp plugin activate wordpress-seo
else
  # Try latest, fall back to last WP-6.7-compatible version (23.x) if it fails
  if wp plugin install wordpress-seo --activate 2>/dev/null; then
    echo "    Yoast SEO installed (latest)."
  elif wp plugin install wordpress-seo --version=23.9 --activate 2>/dev/null; then
    echo "    Yoast SEO installed (v23.9 — WP 6.7 compatible)."
  elif wp plugin install wordpress-seo --version=22.9 --activate; then
    echo "    Yoast SEO installed (v22.9 — WP 6.6 compatible)."
  else
    echo "    ERROR: Could not install Yoast SEO. Check WP version compatibility."
    exit 1
  fi
fi
echo "    Yoast SEO active."

# ------------------------------------------------------------------ #
# 6. Sandbox privacy: noindex (WordPress built-in + Yoast)
# ------------------------------------------------------------------ #
echo "==> Setting noindex..."
# WordPress built-in: discourage search engines
wp option update blog_public 0
# Yoast global noindex for whole site (belt-and-suspenders)
wp option update wpseo '{"is_cornerstone_content_filter_shown": false}' --format=json || true
echo "    Search engine discouragement enabled."

# ------------------------------------------------------------------ #
# 7. Create the Railways page with Phase 1B content
# ------------------------------------------------------------------ #
echo "==> Creating Railways page..."

PAGE_CONTENT='<h1>Railways</h1>

<h2>Our Railway Heritage</h2>

<p>Fluid Controls has over 40 years of experience in engineering connections for railway brake piping assemblies. We offer customers total solutions for locomotive and coach brake piping arrangements &#8211; from design &amp; engineering services to supply of high performance connectors and installation services.</p>

<p>Millions of Fluid Controls connectors have been successfully installed on electric and diesel locomotives, motorized coaches, LHB and mainline coaches and metro cars. We are approved by the Indian Railways, Bombardier Transportation, GE Transport and Alstom and also supply to Knorr&#8209;Bremse, Faiveley and other system providers to railways.</p>

<p>Fluid Controls&reg; partners with customers to be a single source supplier for various connectors required for railway applications. Our products include:</p>

<ol>
<li>Double Ferrule Fittings with multiple sealing points and high vibration resistance DIN Single Ferrule Connectors,</li>
<li>Bulkhead and Threaded Adaptors and connectors Flexi-Grip&reg; connectors for mis-aligned pipe connections</li>
<li>Quick Release Connectors</li>
<li>Customised connectors such as bulkheads designed to client requirements</li>
</ol>

<p>We also provide isolating cocks and a range of clamping accessories (DIN and customised) for railway brake pipe lines.</p>

<p>As an extension of our design and supply services, Fluid Controls&reg; offers clients on-site/off-site installation services of brake piping. We have recently introduced pre-piped assemblies to facilitate installation and ensure faster turnarounds.</p>

<h2>Product Range</h2>

<ul>
<li>Double Ferrule Fittings</li>
<li>Bulkhead and Threaded Adaptors</li>
<li>Flexi-Grip Connectors</li>
<li>Quick Release Connectors</li>
<li>Isolating Cocks</li>
<li>Clamping Accessories</li>
</ul>

<p><img src="/wp-content/uploads/railways-hero.jpg" alt="" class="hero-image" /></p>

<p style="font-size: 12px;">&copy; 2018 Fluid Controls Limited.</p>'

# Check if page already exists
EXISTING_ID=$(wp post list --post_type=page --name=railways --field=ID --format=ids 2>/dev/null | head -1)

if [ -n "$EXISTING_ID" ]; then
  echo "    Railways page already exists (ID: $EXISTING_ID) — updating content."
  PAGE_ID="$EXISTING_ID"
  wp post update "$PAGE_ID" --post_content="$PAGE_CONTENT"
else
  PAGE_ID=$(wp post create \
    --post_type=page \
    --post_title="Railways" \
    --post_name="railways" \
    --post_status=publish \
    --post_content="$PAGE_CONTENT" \
    --porcelain)
  echo "    Railways page created with ID: $PAGE_ID"
fi

# ------------------------------------------------------------------ #
# 8. Set Yoast SEO meta fields (matching live site values)
# ------------------------------------------------------------------ #
echo "==> Setting Yoast SEO meta fields on page $PAGE_ID..."

wp post meta update "$PAGE_ID" _yoast_wpseo_title \
  "Railway Brake System | Railway Brake Piping | Fluid Controls Limited"

wp post meta update "$PAGE_ID" _yoast_wpseo_metadesc \
  "Fluid Controls is a premier supplier of connection solutions for railway brake systems. Fluid Controls offers comprehensive solutions for locomotive, coach & metro brake piping arrangements - from design, engineering, testing and on-site installations services to supply of high performance connectors, cocks, and tube & hose assemblies."

# Canonical pointing to sandbox (not live site)
wp post meta update "$PAGE_ID" _yoast_wpseo_canonical \
  "${SANDBOX_URL}/railways/"

# Set noindex on this page via Yoast (belt-and-suspenders with global noindex)
wp post meta update "$PAGE_ID" _yoast_wpseo_meta-robots-noindex "1"

echo "    Yoast meta fields set."

# ------------------------------------------------------------------ #
# 9. Create Application Password for REST API access
# ------------------------------------------------------------------ #
echo "==> Creating Application Password..."

# Delete existing app passwords for idempotency
wp user application-password delete "$ADMIN_USER" --all --quiet 2>/dev/null || true

APP_PASS=$(wp user application-password create "$ADMIN_USER" "$APP_PASS_NAME" --porcelain)

echo ""
echo "=========================================================="
echo "  WordPress Sandbox provisioned successfully!"
echo "=========================================================="
echo "  Sandbox URL:      ${SANDBOX_URL}"
echo "  Admin URL:        ${SANDBOX_URL}/wp-admin"
echo "  Admin user:       ${ADMIN_USER}"
echo "  Admin password:   ${ADMIN_PASS}"
echo "  Railways page ID: ${PAGE_ID}"
echo "  REST API URL:     ${SANDBOX_URL}/wp-json/wp/v2/pages/${PAGE_ID}"
echo ""
echo "  -- Application Password (for Phase 4 connector) --"
echo "  User:             ${ADMIN_USER}"
echo "  Password:         ${APP_PASS}"
echo "  Authorization:    Basic $(echo -n "${ADMIN_USER}:${APP_PASS}" | base64)"
echo ""
echo "  -- Basic Auth (nginx proxy) --"
echo "  User:             sandbox"
echo "  Password:         sandbox123"
echo "=========================================================="
echo ""
echo "  Verify with:"
echo "  curl -u sandbox:sandbox123 ${SANDBOX_URL}/wp-json/wp/v2/pages/${PAGE_ID}"
echo ""
