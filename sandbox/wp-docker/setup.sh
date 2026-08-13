#!/bin/bash

# setup.sh - Run this INSIDE the wpcli container to initialize the sandbox

echo "Waiting for database to be ready..."
sleep 10 # simple wait

echo "Installing WordPress..."
wp core install \
  --url=http://localhost:8080 \
  --title="Fluid Controls Sandbox" \
  --admin_user=admin \
  --admin_password=admin_password \
  --admin_email=admin@example.com

echo "Setting up Application Password..."
# We generate a known application password for the connector to use
# The Application Passwords plugin is part of WP core as of 5.6
wp user application-password create admin rankengine-connector --porcelain > /tmp/app_password.txt
APP_PASS=$(cat /tmp/app_password.txt)
echo "Application Password generated: $APP_PASS"

echo "Installing and activating Yoast SEO..."
wp plugin install wordpress-seo --activate

echo "Creating the Railways product page..."
# Create the page with some baseline HTML
PAGE_CONTENT='<p>Fluid Controls Ltd is a recognized supplier of fluid control systems for the railways industry. We provide a broad range of high-performance components.</p>
<img src="/images/railway-system.jpg" />
<h2>Product Range</h2>
<p>Our solutions for the railway sector include:</p>
<ul>
    <li>Control valves</li>
    <li>Double ferrule fittings</li>
    <li>Isolation valves</li>
</ul>'

PAGE_ID=$(wp post create \
  --post_type=page \
  --post_title="Railways" \
  --post_status=publish \
  --post_content="$PAGE_CONTENT" \
  --porcelain)

echo "Page created with ID: $PAGE_ID"

echo "Setting Yoast SEO meta fields for the page..."
# The live site has a meta description, so we set a baseline one here
wp post meta set $PAGE_ID _yoast_wpseo_metadesc "Fluid Controls is a supplier to the railway industry for various control equipment."
wp post meta set $PAGE_ID _yoast_wpseo_title "Railways - Fluid Controls"

echo ""
echo "=========================================================="
echo "WordPress Sandbox initialized successfully!"
echo "Target Page ID: $PAGE_ID"
echo "REST API URL: http://localhost:8080/wp-json/wp/v2/pages/$PAGE_ID"
echo "Admin User: admin"
echo "App Password: $APP_PASS"
echo "=========================================================="
