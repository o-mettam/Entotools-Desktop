// Extracted verbatim from EntoTools-Production templates/collection_database.html @ f948578
// (the website's CSV import). Used by tests/test_csvio.py to prove the Python port matches.

function parseCSV(text) {
            const src = text.charCodeAt(0) === 0xFEFF ? text.slice(1) : text;
            const rows = [];
            let row = [];
            let field = '';
            let inQuotes = false;
            const pushField = () => { row.push(field.trim()); field = ''; };
            const pushRow = () => {
                pushField();
                if (row.some(c => c !== '')) rows.push(row);
                row = [];
            };
            for (let i = 0; i < src.length; i++) {
                const ch = src[i];
                if (inQuotes) {
                    if (ch === '"') {
                        if (src[i + 1] === '"') { field += '"'; i++; }
                        else inQuotes = false;
                    } else field += ch;
                } else if (ch === '"') inQuotes = true;
                else if (ch === ',') pushField();
                else if (ch === '\r') { if (src[i + 1] === '\n') i++; pushRow(); }
                else if (ch === '\n') pushRow();
                else field += ch;
            }
            if (field !== '' || row.length) pushRow();
            return rows;
        }

function parse12hTo24h(str) {
            if (!str) return '';
            str = str.trim();
            // If already in 24h format (HH:MM), return as-is
            if (/^\d{1,2}:\d{2}$/.test(str)) return str;
            const match = str.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
            if (!match) return '';
            let h = parseInt(match[1]);
            const m = match[2];
            const ampm = match[3].toUpperCase();
            if (ampm === 'PM' && h !== 12) h += 12;
            if (ampm === 'AM' && h === 12) h = 0;
            return String(h).padStart(2, '0') + ':' + m;
        }

function parseTimeRangeStart(timeStr) {
            if (!timeStr) return '';
            // Handle "HH:MM - HH:MM" (24h stored format)
            if (timeStr.includes(' - ') && /^\d{2}:\d{2}/.test(timeStr)) return timeStr.split(' - ')[0].trim();
            // Handle "1:00 PM – 4:00 PM" (12h display format)
            const sep = timeStr.includes('–') ? '–' : timeStr.includes(' - ') ? ' - ' : null;
            if (sep) return parse12hTo24h(timeStr.split(sep)[0].trim());
            return parse12hTo24h(timeStr.trim());
        }

function parseTimeRangeEnd(timeStr) {
            if (!timeStr) return '';
            // Handle "HH:MM - HH:MM" (24h stored format)
            if (timeStr.includes(' - ') && /^\d{2}:\d{2}/.test(timeStr)) {
                const parts = timeStr.split(' - ');
                return parts.length > 1 ? parts[1].trim() : '';
            }
            // Handle "1:00 PM – 4:00 PM" (12h display format)
            const sep = timeStr.includes('–') ? '–' : timeStr.includes(' - ') ? ' - ' : null;
            if (sep) {
                const parts = timeStr.split(sep);
                return parts.length > 1 ? parse12hTo24h(parts[1].trim()) : '';
            }
            return '';
        }

function csvRowToData(headerMap, vals) {
            const g = (name) => vals[headerMap[name]] ?? '';
            const num = (name) => {
                const v = g(name);
                if (v === '') return null;
                const parsed = parseFloat(v);
                return isNaN(parsed) ? null : parsed;
            };

            const coordsEstimated = g('Coordinates Estimated').toLowerCase();
            const gddRaw = g('mGDD');
            let gddStart = 0, gddEnd = 0, isRange = false;
            // A range looks like "120 - 340"; a single negative value ("-5") must
            // not be mistaken for one.
            const gddRange = gddRaw.match(/^\s*(-?\d+(?:\.\d+)?)\s*[-–]\s*(-?\d+(?:\.\d+)?)\s*$/);
            if (gddRange) {
                gddStart = parseFloat(gddRange[1]) || 0;
                gddEnd = parseFloat(gddRange[2]) || 0;
                isRange = true;
            } else {
                gddStart = parseFloat(gddRaw) || 0;
                gddEnd = gddStart;
            }

            const dateEnd = g('Date End');
            if (dateEnd && dateEnd !== g('Date Start')) isRange = true;

            return {
                specimenId: g('Specimen ID'),
                identification: g('Specimen Identification'),
                numSpecimens: g('Number of Specimens'),
                siteName: g('Site Name'),
                location: g('Location'),
                country: g('Country'),
                lat: num('Latitude'),
                lon: num('Longitude'),
                inputMode: coordsEstimated === 'yes' ? 'city' : 'latlon',
                elevation: num('Elevation (m)'),
                dateStart: g('Date Start'),
                dateEnd: dateEnd || g('Date Start'),
                isRange,
                sunset: g('Sunset'),
                timeOfCollection: g('Time of Collection'),
                timeStart: parseTimeRangeStart(g('Time of Collection')),
                timeEnd: parseTimeRangeEnd(g('Time of Collection')),
                collector: g('Collector'),
                identifier: g('Determiner'),
                highTemp: num('High Temp (F)'),
                lowTemp: num('Low Temp (F)'),
                avgTemp: num('Avg Temp (F)'),
                tempAtTime: num('Temp at Collection (F)'),
                gddStart, gddEnd,
                humidity: { atTime: null, avg: num('Humidity (%)') },
                rainfallWeek: num('Rainfall Last 7 Days (in)'),
                rainfallMonth: num('Rainfall Last 30 Days (in)'),
                stationName: g('Weather Station'),
                stationId: g('Station ID'),
                stationDist: num('Station Distance (mi)'),
                provider: g('Data Provider'),
                baseTemp: num('mGDD Base Temp (F)'),
                maxTemp: num('mGDD Max Temp (F)'),
                accumStartMD: g('mGDD Accum Start Date'),
                collectionMethod: g('Collection Method'),
                userNotes: g('Notes'),
            };
        }

module.exports = { parseCSV, csvRowToData };