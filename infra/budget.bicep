// Msimulizi — monthly Azure cost budget and alerts.
//
// Deploy separately from the main stack so budget notifications can target
// real operators without committing personal email addresses:
//
//   az deployment group create \
//     -g rg-msimulizi-demo2 \
//     -f infra/budget.bicep \
//     -p budgetName=msim-msimulizi-demo2-monthly \
//        amount=100 \
//        contactEmails='["operator@example.com"]'

targetScope = 'resourceGroup'

@description('Budget resource name, unique within the resource group.')
param budgetName string

@description('Monthly budget amount in USD.')
param amount int = 100

@description('Email addresses that receive threshold notifications.')
param contactEmails array

@description('Budget period start (UTC, YYYY-MM-DD). Use the first day of the month.')
param startDate string = '2026-10-01'

@description('Budget period end (UTC, YYYY-MM-DD).')
param endDate string = '2027-10-01'

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: budgetName
  properties: {
    category: 'Cost'
    amount: amount
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: '${startDate}T00:00:00Z'
      endDate: '${endDate}T00:00:00Z'
    }
    notifications: {
      Actual_50: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 50
        thresholdType: 'Actual'
        contactEmails: contactEmails
        contactRoles: ['Owner']
        locale: 'en-us'
      }
      Actual_80: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: contactEmails
        contactRoles: ['Owner']
        locale: 'en-us'
      }
      Actual_100: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: contactEmails
        contactRoles: ['Owner']
        locale: 'en-us'
      }
      Forecast_100: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: contactEmails
        contactRoles: ['Owner']
        locale: 'en-us'
      }
    }
  }
}

output budgetId string = budget.id
output budgetName string = budget.name
