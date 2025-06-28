#ifndef __SIM_ROLLING_H__
#define __SIM_ROLLING_H__

#include <sqlite3.h>
#include <unistd.h>

#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstring>

#include "base/types.hh"

namespace gem5{
enum DataType
{
    UINT64,
    TEXT,
    OHTER
};

static int callback(void *NotUsed, int argc, char **argv, char **azColName){
  return 0;
}

class Rolling
{
  private:
    bool enabled;
    Counter interval;
    Counter base;
    Counter value_interval;
    Counter base_interval;
    std::string db_path;
    sqlite3 *mem_db;
    std::string tableName;
    std::vector<std::pair<std::string, DataType>> fields_vec;

  public:
    Rolling(const char *name, const char *desc = nullptr,
           Counter intv = 1000, bool enable_rolling = false, const std::string &db_path = "")
           : interval(intv), base(0), value_interval(0),
             base_interval(0), enabled(enable_rolling), tableName(name), db_path(db_path)
    {
      if (enabled) {
        int rc = sqlite3_open(":memory:", &mem_db);
        if (rc) {
          sqlite3_close(mem_db);
          fatal("Can't open database: %s\n", sqlite3_errmsg(mem_db));
        }

        fields_vec = {
            std::make_pair("yAxisPt", UINT64),
            std::make_pair("xAxisPt", UINT64),
        };
        tableName += "_rolling_0";
        // create table
        char sql[1024];
        int pos = 0;
        pos = sprintf(sql,
          "CREATE TABLE %s(" \
          "ID INTEGER PRIMARY KEY AUTOINCREMENT, " \
          "TICK INT NOT NULL", tableName.c_str());
        for (auto it = fields_vec.begin(); it != fields_vec.end(); it++) {
          switch (it->second) {
            case UINT64:
              pos += sprintf(sql+pos, ",%s INT NOT NULL", it->first.c_str());
              break;
            case TEXT:
              pos += sprintf(sql+pos, ",%s TEXT", it->first.c_str());
              break;
            default:
              fatal("Unknown data type");
          }
        }
        pos += sprintf(sql+pos, ");");
        assert(pos < 1024);
        printf("%s\n", sql);
        char *zErrMsg;
        rc = sqlite3_exec(mem_db, sql, callback, 0, &zErrMsg);
        if (rc != SQLITE_OK) {
          fatal("SQL error: %s\n", zErrMsg);
        } else {
          warn("Table created: %s\n", tableName.c_str());
        }

        registerExitCallback([this](){
          // std::string db_path("./m5out/ipc_rolling.db");
          fatal_if(this->db_path == "", "db file path is not given!");
          warn("saving memdb to %s ...\n", this->db_path.c_str());
          sqlite3 *disk_db;
          sqlite3_backup *pBackup;
          int rc = sqlite3_open(this->db_path.c_str(), &disk_db);
          if (rc == SQLITE_OK){
            pBackup = sqlite3_backup_init(disk_db, "main", mem_db, "main");
            if (pBackup){
              (void)sqlite3_backup_step(pBackup, -1);
              (void)sqlite3_backup_finish(pBackup);
            }
            rc = sqlite3_errcode(disk_db);
          }
          sqlite3_close(disk_db);
        });
      }
    }

    void operator++(int) { value_interval++; }

    void operator++() { assert(false && "Not implemented\n"); }

    void operator+=(Counter v) { value_interval += v; }

    Counter get_value_and_clean() {
      Counter temp = value_interval;
      value_interval = 0;
      return temp;
    }

    Counter get_base_and_clean() {
      base_interval = 0;
      return base;
    }

    void roll(Counter v)
    {
      // printf("Tick: %lu\n", curTick());
      base += v;
      base_interval += v;
      bool dump = (base_interval >= interval);
      if (dump && enabled)
      {
        Counter y_value = get_value_and_clean();
        Counter x_value = get_base_and_clean();
        uint64_t tick = curTick() / 500;

        char sql[1024];
        int pos = 0;
        pos = sprintf(sql, "INSERT INTO %s(TICK", tableName.c_str());
        for (auto it = fields_vec.begin(); it != fields_vec.end(); it++) {
          pos += sprintf(sql+pos, ",%s", it->first.c_str());
        }
        pos += sprintf(sql+pos, ") VALUES(%ld", tick);
        pos += sprintf(sql+pos, ",%ld", y_value);
        pos += sprintf(sql+pos, ",%ld", x_value);
        pos += sprintf(sql+pos, ");");
        assert(pos < 1024);
        char *zErrMsg;
        int rc = sqlite3_exec(mem_db, sql, callback, 0, &zErrMsg);
        if (rc != SQLITE_OK) {
          fatal("SQL error: %s\n", zErrMsg);
        };
      }
    }
};

} // namespace gem5

#endif
