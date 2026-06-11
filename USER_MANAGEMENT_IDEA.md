# USER MANAGEMENT IDEA

## Scaling Operators: Single Building vs. City Level

Even for a single building, a client will almost never have just one operator. Commercial buildings run 24/7, meaning they will have a rotation of 3 to 5 operators working in shifts (morning, evening, night) to cover the dashboard at all times.

When a client scales from a single building to an entire city or a multi-property portfolio, the user management architecture must introduce Site-Based Access Control.

**Here is how that plays out:**

**On-Site Operators:** Users are scoped to specific locations. An operator physically stationed at "Building A" should only receive alerts and see dashboard data for "Building A". You do not want an operator in District 1 getting flooded with water leak alerts for a building in District 7.

**Central Command Operators:** Large urban developments often have a centralized monitoring hub. These operators need a "Cluster" or "Global" scope. They monitor the macro-level dashboard for all buildings across the city and use their radio or internal systems to dispatch the local on-site technicians.

**Necessary Information for an Operator Profile**
To handle both the authentication and the operational routing (making sure the right person gets the right alert), your system needs a specific set of data fields when the Admin creates an Operator account.

**Here are the essential fields you need in your database and UI form:**

**Full Name:** Required for the system's audit logs. When an anomaly is marked as "Resolved," the system needs to record exactly which operator handled it.

**Username / Login ID:** Often an employee ID or company email used for standard authentication.

**Contact Number:** This is critical. For high-severity anomalies (like a major power spike or a flooded floor), the system needs to trigger an immediate SMS, Zalo, or Telegram webhook. An email is too slow for emergency BMS alerts.

**Role Designation:** An ENUM or strictly typed string set to Operator to ensure they are locked out of the AI model training and financial forecasting modules.

**Assigned Sites / Scope ID:** This is the key to scaling. Instead of just a role, the operator needs a data array mapping them to physical locations (e.g., assigned_sites: ["Building_1"] or assigned_sites: ["Building_1", "Building_2"]). The backend uses this array to filter the live anomaly feed so the user only sees what they are responsible for.

## Admin Profile (The Multi-Level Manager)

Because the platform scales, Admins must also be hierarchical. A facility manager in charge of Building A should not be able to view financial forecasts or create user accounts for Building B. However, a City Director needs to see everything.

**Full Name & Contact Info:** Standard fields for audit logs (e.g., tracking who exported a forecast or changed a system threshold).

**Username / Email:** Standard login credential.

**Role Designation:** Admin.

**Assigned Sites:** Exactly like the Operator, a standard Admin needs an array mapping them to physical locations (e.g., ["Building_A"]). They can only view analytics and manage users within this scope.

**Global Access Flag:** A simple boolean (is_global_admin: true/false). If true, the system ignores the assigned sites array and grants them "City-level" read/write access to all properties, forecasts, and user management modules.

## AI Engineer Profile (The Centralized Tech)

Unlike Operators and Admins who are tied to physical building management, the AI Engineer is almost always a centralized, corporate-level role. They don't care about a single building; they care about the aggregate data from all buildings to train better models.

**Full Name & Contact Info:** Standard fields.

**Username / Email:** Standard login credential.

**Role Designation:** AI_Engineer.

**Data Scope (Global Read):** AI Engineers typically do not use an "Assigned Sites" array. To train an accurate model, they need access to the entire historical data lake. Their system scope is usually Global Read across all databases, meaning they can pull training data from any site.

**Functional Restriction:** Their restriction isn't by location, it is by function. They can pull all the data they want, but the backend must block them from acknowledging live operational alerts or approving financial budgets.
