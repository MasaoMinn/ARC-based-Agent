package com.example.springwebtlias.controller;

import com.example.springwebtlias.pojo.Dept;
import com.example.springwebtlias.pojo.Result;
import com.example.springwebtlias.service.DeptService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@Slf4j
@RestController
@RequestMapping("/depts")
public class DeptController {

    @Autowired
   private DeptService deptService;

    @GetMapping
    public Result list()
    {
        log.info("查询所有数据");
       List<Dept> depts = deptService.list();
        return Result.success(depts);
    }

    @DeleteMapping("/{id}")
    public Result delete(@PathVariable int id)
    {
        log.info("删除id{}数据",id);
        deptService.delete(id);
        return Result.success();
    }

    @PostMapping
    public Result add(@RequestBody Dept dept)
    {
        log.info("新增数据{}",dept);
        deptService.add(dept);
        return Result.success();
    }

    @GetMapping("/{id}")
    public Result selectById(@PathVariable Integer id)
    {
        log.info("查询id{}的数据",id);
        Dept dept = deptService.selectById(id);
        return Result.success(dept);
    }

    @PutMapping
    public Result change(@RequestBody Dept dept)
    {
        log.info("修改数据为{}",dept);
        deptService.change(dept);
        return Result.success();
    }
}
