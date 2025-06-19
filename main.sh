#!/bin/bash

# Email notification script for CNGFW Azure VNet Peering Reports
# This script handles the email sending logic with proper formatting and error handling

set -euo pipefail

# Configuration
TEMP_DIR="/tmp/email_notifications_$$"

# Create temporary directory for email processing
mkdir -p "$TEMP_DIR"

# Cleanup function
cleanup() {
    echo "🧹 Cleaning up temporary files..."
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Error handling function
handle_error() {
    local error_message="$1"
    log "❌ ERROR: $error_message"
    
    # Send error notification email
    send_error_notification "$error_message"
    exit 1
}

# Function to validate required environment variables
validate_environment() {
    log "🔍 Validating environment variables..."
    
    local required_vars=(
        "SENDGRID_API_KEY"
        "FROM_EMAIL"
        "TO_EMAIL"
        "FAILURE_TO_EMAIL"
        "CI_PIPELINE_ID"
        "CI_PROJECT_NAME"
        "CI_PIPELINE_URL"
    )
    
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var:-}" ]]; then
            handle_error "Required environment variable $var is not set"
        fi
    done
    
    log "✅ Environment validation completed"
}

# Function to check file existence and readability
check_file() {
    local file_path="$1"
    if [[ -f "$file_path" && -r "$file_path" ]]; then
        return 0
    else
        return 1
    fi
}

# Function to encode file to base64
encode_file_base64() {
    local file_path="$1"
    if check_file "$file_path"; then
        base64 -w 0 "$file_path"
    else
        echo ""
    fi
}

# Function to get file size in human readable format
get_file_size() {
    local file_path="$1"
    if check_file "$file_path"; then
        du -h "$file_path" | cut -f1
    else
        echo "0B"
    fi
}

# Function to create attachment JSON
create_attachment_json() {
    local file_path="$1"
    local content_type="$2"
    local filename="$3"
    
    if ! check_file "$file_path"; then
        echo ""
        return
    fi
    
    local content
    content=$(encode_file_base64 "$file_path")
    if [[ -z "$content" ]]; then
        echo ""
        return
    fi
    
    local size
    size=$(get_file_size "$file_path")
    
    # Create JSON manually to avoid dependencies
    cat << JSON_END
{
  "content": "$content",
  "type": "$content_type",
  "filename": "$filename",
  "disposition": "attachment"
}
JSON_END
}

# Function to generate comprehensive email body
generate_comprehensive_email_body() {
    local pipeline_status="$1"
    local report_summary="$2"
    
    cat << EMAIL_BODY_END
📊 CNGFW - Azure VNet Peering Report

Dear Team,

This email contains the automated report for Cloud Next Generation Firewall (CNGFW) Azure Virtual Network peering operations.

═══════════════════════════════════════════════════════════
📋 EXECUTION SUMMARY
═══════════════════════════════════════════════════════════

Pipeline ID: ${CI_PIPELINE_ID}
Project: ${CI_PROJECT_NAME}
Execution Date: $(date '+%Y-%m-%d %H:%M:%S UTC')
Status: ${pipeline_status}
Pipeline URL: ${CI_PIPELINE_URL}

═══════════════════════════════════════════════════════════
📈 REPORT DETAILS
═══════════════════════════════════════════════════════════

${report_summary}

═══════════════════════════════════════════════════════════
📎 ATTACHMENTS
═══════════════════════════════════════════════════════════

This email includes the following attachments:
• HTML Report: Comprehensive visual report with charts and detailed analysis
• Log File: Detailed execution logs for troubleshooting and audit purposes

═══════════════════════════════════════════════════════════
🔍 NEXT STEPS
═══════════════════════════════════════════════════════════

1. Review the attached HTML report for detailed peering status
2. Check the log file for any warnings or informational messages
3. Address any issues highlighted in the report
4. Monitor the next scheduled execution

═══════════════════════════════════════════════════════════

For technical support or questions regarding this report, please contact the Security Engineering team.

Best regards,
GitLab CI/CD Automation System
EMAIL_BODY_END
}

# Function to generate failure email body
generate_failure_email_body() {
    local error_details="$1"
    
    cat << FAILURE_BODY_END
🚨 CNGFW - Azure VNet Peering FAILURE ALERT

URGENT: The CNGFW Azure VNet Peering operation has encountered critical issues.

═══════════════════════════════════════════════════════════
❌ FAILURE DETAILS
═══════════════════════════════════════════════════════════

Pipeline ID: ${CI_PIPELINE_ID}
Project: ${CI_PROJECT_NAME}
Failure Time: $(date '+%Y-%m-%d %H:%M:%S UTC')
Pipeline URL: ${CI_PIPELINE_URL}

Error Details:
${error_details}

═══════════════════════════════════════════════════════════
🔧 IMMEDIATE ACTIONS REQUIRED
═══════════════════════════════════════════════════════════

1. Investigate the root cause of the failure
2. Check Azure service health and connectivity
3. Verify service principal permissions and credentials
4. Review the attached logs for detailed error information
5. Manually trigger the pipeline after resolving issues

═══════════════════════════════════════════════════════════
📞 ESCALATION
═══════════════════════════════════════════════════════════

If this issue persists or requires immediate attention:
• Contact: Security Engineering Team (On-Call)
• Escalation: Infrastructure Team Lead
• Priority: HIGH

═══════════════════════════════════════════════════════════

This is an automated alert. Please do not reply to this email.
FAILURE_BODY_END
}

# Function to escape JSON string
escape_json_string() {
    local string="$1"
    # Escape quotes, backslashes, and newlines for JSON
    echo "$string" | sed 's/\\/\\\\/g' | sed 's/"/\\"/g' | sed ':a;N;$!ba;s/\n/\\n/g'
}

# Function to send email using SendGrid API
send_email() {
    local to_email="$1"
    local subject="$2"
    local email_body="$3"
    local attachments_json="$4"
    
    log "📧 Sending email to: $to_email"
    log "📧 Subject: $subject"
    
    # Escape email body for JSON
    local escaped_body
    escaped_body=$(escape_json_string "$email_body")
    
    # Create email payload - build JSON manually to avoid dependencies
    local email_payload
    email_payload=$(cat << JSON_PAYLOAD_END
{
    "personalizations": [
        {
            "to": [{"email": "$to_email"}],
            "subject": "$subject"
        }
    ],
    "from": {"email": "$FROM_EMAIL"},
    "content": [
        {
            "type": "text/plain",
            "value": "$escaped_body"
        }
    ],
    "attachments": $attachments_json
}
JSON_PAYLOAD_END
)
    
    # Save payload to temp file for debugging
    echo "$email_payload" > "$TEMP_DIR/email_payload.json"
    
    # Send email via SendGrid API
    local response
    response=$(curl -s -w "\n%{http_code}" -X POST "https://api.sendgrid.com/v3/mail/send" \
        -H "Authorization: Bearer $SENDGRID_API_KEY" \
        -H "Content-Type: application/json" \
        -d "$email_payload")
    
    local http_code
    http_code=$(echo "$response" | tail -n1)
    local response_body
    response_body=$(echo "$response" | head -n -1)
    
    if [[ "$http_code" -eq 202 ]]; then
        log "✅ Email sent successfully to $to_email"
        return 0
    else
        log "❌ Failed to send email to $to_email (HTTP: $http_code)"
        log "Response: $response_body"
        return 1
    fi
}

# Function to send error notification
send_error_notification() {
    local error_message="$1"
    
    local error_body
    error_body=$(cat << ERROR_EMAIL_END
🚨 CRITICAL: Email Notification System Failure

The CNGFW Azure VNet Peering pipeline completed, but the email notification system encountered an error.

Error: $error_message

Pipeline ID: ${CI_PIPELINE_ID:-"Unknown"}
Time: $(date '+%Y-%m-%d %H:%M:%S UTC')

Please check the pipeline logs and manual review the reports in the artifacts.

This requires immediate attention from the DevOps team.
ERROR_EMAIL_END
)
    
    local escaped_error_body
    escaped_error_body=$(escape_json_string "$error_body")
    
    # Try to send basic error notification without attachments
    curl -s -X POST "https://api.sendgrid.com/v3/mail/send" \
        -H "Authorization: Bearer $SENDGRID_API_KEY" \
        -H "Content-Type: application/json" \
        -d "{
            \"personalizations\": [
                {
                    \"to\": [{\"email\": \"$FAILURE_TO_EMAIL\"}],
                    \"subject\": \"CRITICAL: CNGFW Pipeline Email Notification Failure\"
                }
            ],
            \"from\": {\"email\": \"$FROM_EMAIL\"},
            \"content\": [
                {
                    \"type\": \"text/plain\",
                    \"value\": \"$escaped_error_body\"
                }
            ]
        }" || true
}

# Main execution function
main() {
    log "🚀 Starting email notification process..."
    
    # Validate environment
    validate_environment
    
    # Define file paths
    local comprehensive_report="${COMPREHENSIVE_REPORT_PATH:-pipelines/__py/vnet_peering_report.html}"
    local failure_report="${FAILURE_REPORT_PATH:-pipelines/__py/vnet_peering_failure_report.html}"
    local log_file="${LOG_FILE_PATH:-pipelines/__py/vnet_peering.log}"
    
    # Initialize attachment arrays
    local attachments=()
    
    # Process comprehensive report attachment
    if check_file "$comprehensive_report"; then
        log "📎 Processing comprehensive report attachment..."
        local report_attachment
        report_attachment=$(create_attachment_json "$comprehensive_report" "text/html" "vnet_peering_report.html")
        if [[ -n "$report_attachment" ]]; then
            attachments+=("$report_attachment")
            log "✅ Comprehensive report attachment prepared ($(get_file_size "$comprehensive_report"))"
        fi
    else
        log "⚠️  Comprehensive report not found: $comprehensive_report"
    fi
    
    # Process log file attachment
    if check_file "$log_file"; then
        log "📎 Processing log file attachment..."
        local log_attachment
        log_attachment=$(create_attachment_json "$log_file" "text/plain" "vnet_peering.log")
        if [[ -n "$log_attachment" ]]; then
            attachments+=("$log_attachment")
            log "✅ Log file attachment prepared ($(get_file_size "$log_file"))"
        fi
    else
        log "⚠️  Log file not found: $log_file"
    fi
    
    # Create attachments JSON array
    local attachments_json="[]"
    if [[ ${#attachments[@]} -gt 0 ]]; then
        # Manually build JSON array
        attachments_json="["
        for i in "${!attachments[@]}"; do
            if [[ $i -gt 0 ]]; then
                attachments_json="$attachments_json,"
            fi
            attachments_json="$attachments_json${attachments[$i]}"
        done
        attachments_json="$attachments_json]"
    fi
    
    # Determine pipeline status and generate report summary
    local pipeline_status="SUCCESS"
    local report_summary="The VNet peering analysis completed successfully. Please review the attached reports for detailed information."
    
    if check_file "$failure_report"; then
        pipeline_status="PARTIAL SUCCESS WITH WARNINGS"
        report_summary="The VNet peering analysis completed with some warnings or issues. Please review the failure report for details."
    fi
    
    # Generate and send comprehensive email
    local comprehensive_body
    comprehensive_body=$(generate_comprehensive_email_body "$pipeline_status" "$report_summary")
    
    if ! send_email "$TO_EMAIL" "CNGFW - Azure VNet Peering Report" "$comprehensive_body" "$attachments_json"; then
        handle_error "Failed to send comprehensive report email"
    fi
    
    # Send failure notification if failure report exists
    if check_file "$failure_report"; then
        log "⚠️  Failure report detected, sending failure notification..."
        
        local failure_content
        if failure_content=$(cat "$failure_report" 2>/dev/null); then
            local failure_body
            failure_body=$(generate_failure_email_body "$failure_content")
            
            if ! send_email "$FAILURE_TO_EMAIL" "🚨 CNGFW - Azure VNet Peering FAILURE ALERT" "$failure_body" "[]"; then
                log "❌ Failed to send failure notification email"
            else
                log "✅ Failure notification sent successfully"
            fi
        else
            log "❌ Could not read failure report content"
        fi
    fi
    
    log "✅ Email notification process completed successfully"
}

# Execute main function
main "$@"